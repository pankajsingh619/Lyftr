"""Safe real-provider acceptance test for the running Lyftr AI backend.

Usage:
    python scripts/verify_live_provider.py --base-url http://127.0.0.1:8000

Prerequisites:
    - Backend is running with >= 2 real keys in LLM_API_KEYS
    - ENABLE_FAILURE_SIMULATION=true
    - CACHE_ENABLED=true

Skips gracefully (NOT TESTED) when real credentials are unavailable.
Never prints API keys or raw credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
import urllib.error
import urllib.request


def http_json(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    req_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return exc.code, parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real LLM provider inference, cache, and failover.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    # 1. Health check
    try:
        status, health = http_json(f"{base}/health")
    except urllib.error.URLError as exc:
        print(f"SKIPPED (NOT TESTED): Cannot reach backend at {base} ({exc.reason})")
        return 0

    print(f"[1/9] GET /health -> {status} {health}")
    if status == 503 and health.get("detail") == "no LLM keys configured":
        print("SKIPPED (NOT TESTED): No real LLM_API_KEYS configured on backend.")
        return 0

    assert status == 200 and health.get("status") == "ok", f"Backend unhealthy: {health}"
    if health.get("keys_configured", 0) < 2:
        print("SKIPPED (NOT TESTED): At least 2 configured keys are required for failover verification.")
        return 0
    assert health.get("cache_enabled") is True, "Cache must be enabled"

    nonce = uuid.uuid4().hex[:8]
    prompt = f"Reply with exactly three words: Lyftr acceptance {nonce}."

    # 2. Live inference using key_1 (first session)
    s1 = f"acc-live-{nonce}"
    status, r1 = http_json(
        f"{base}/chat",
        method="POST",
        body={"session_id": s1, "message": prompt},
    )
    if status in (401, 403):
        print(f"AUTH FAILURE ({status}): Verify real API credentials in .env ({r1.get('detail')}).")
        return 1
    if status == 503:
        print(f"PROVIDER UNAVAILABLE (503): Verify real API keys / quota ({r1.get('detail')}).")
        return 1

    print(f"[2/9] Live inference (key_1) -> {status} meta={r1.get('metadata')}")
    assert status == 200, f"Expected 200, got {status}: {r1}"
    m1 = r1["metadata"]
    assert m1["resolution_source"] == "LIVE_INFERENCE"
    assert m1["key_id"] == "key_1"
    assert m1["fallback_attempts"] == 0
    assert m1["input_tokens"] > 0 and m1["output_tokens"] > 0

    # 3. Cross-session cache hit (second new session, identical first prompt)
    s2 = f"acc-cache-{nonce}"
    status, r2 = http_json(
        f"{base}/chat",
        method="POST",
        body={"session_id": s2, "message": prompt},
    )
    print(f"[3/9] Cross-session cache hit -> {status} meta={r2.get('metadata')}")
    assert status == 200
    m2 = r2["metadata"]
    assert r2["reply"] == r1["reply"], "Cached reply must match original reply"
    assert m2["resolution_source"] == "LLM_CACHE"
    assert m2["key_id"] is None
    assert m2["fallback_attempts"] == 0
    assert m2["input_tokens"] == m1["input_tokens"]
    assert m2["output_tokens"] == m1["output_tokens"]
    assert m2["latency_ms"] >= 0
    if m2["latency_ms"] >= m1["latency_ms"]:
        print(f"   Warning: cache latency ({m2['latency_ms']} ms) >= live latency ({m1['latency_ms']} ms) due to network jitter")

    # 4. Independent key_2 verification & failover (key_1=429)
    s3 = f"acc-failover-{nonce}"
    status, r3 = http_json(
        f"{base}/chat",
        method="POST",
        headers={"X-Simulate-Failure": "key_1=429"},
        body={"session_id": s3, "message": prompt},
    )
    print(f"[4/9] Simulated key_1=429 failover -> {status} meta={r3.get('metadata')}")
    assert status == 200, f"Expected failover 200, got {status}: {r3}"
    m3 = r3["metadata"]
    assert m3["resolution_source"] == "LIVE_INFERENCE"
    assert m3["key_id"] == "key_2"
    assert m3["fallback_attempts"] == 1

    # 5. Multi-turn memory in session s3
    status, r4 = http_json(
        f"{base}/chat",
        method="POST",
        body={"session_id": s3, "message": "What was the exact 8-character code I just sent?"},
    )
    print(f"[5/9] Multi-turn memory -> {status} reply={r4.get('reply')!r} in_tokens={r4.get('metadata', {}).get('input_tokens')}")
    assert status == 200
    assert nonce in r4["reply"], "Assistant did not retain turn-1 context"

    # 6. All keys failing -> 503 without polluting history
    status, r5 = http_json(
        f"{base}/chat",
        method="POST",
        headers={"X-Simulate-Failure": "*=429"},
        body={"session_id": s3, "message": "This must fail with 503"},
    )
    print(f"[6/9] Wildcard failure (*=429) -> {status} {r5}")
    assert status == 503 and r5 == {"detail": "all providers unavailable"}

    # 7. Session history verification (4 messages, oldest first, no failed turn)
    status, hist = http_json(f"{base}/sessions/{s3}/messages")
    print(f"[7/9] GET /sessions/{s3}/messages -> {status} count={len(hist.get('messages', []))}")
    assert status == 200
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant", "user", "assistant"]

    # 8. Validation 422 check
    status, err422 = http_json(
        f"{base}/chat",
        method="POST",
        body={"session_id": s3, "message": "   "},
    )
    print(f"[8/9] Empty message validation -> {status}")
    assert status == 422 and "detail" in err422

    # 9. Unknown session 404 check
    status, err404 = http_json(f"{base}/sessions/nonexistent-{nonce}/messages")
    print(f"[9/9] Unknown session history -> {status} {err404}")
    assert status == 404 and err404 == {"detail": "session not found"}

    print("ALL 9 REAL-PROVIDER ACCEPTANCE CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
