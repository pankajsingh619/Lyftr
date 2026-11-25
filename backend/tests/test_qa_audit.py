from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app


def make_settings(
    db_path: Path,
    api_keys: str = "secret-key-1,secret-key-2",
    enable_failure_simulation: bool = True,
    cache_enabled: bool = True,
    allowed_origins: str = "http://localhost:3000, https://app.example.com/",
) -> Settings:
    return Settings(
        LLM_API_KEYS=api_keys,
        LLM_MODEL="gemini/gemini-2.0-flash",
        DATABASE_URL=f"sqlite:///{db_path.as_posix()}",
        ALLOWED_ORIGINS=allowed_origins,
        ENABLE_FAILURE_SIMULATION=enable_failure_simulation,
        CACHE_ENABLED=cache_enabled,
        CACHE_TYPE="local",
    )


def build_response(content: str, prompt_tokens: int = 10, completion_tokens: int = 5):
    return litellm.ModelResponse(
        id="chatcmpl-qa",
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        model="gemini/gemini-2.0-flash",
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    )


@pytest.fixture
def qa_client(tmp_path: Path):
    clients: list[TestClient] = []

    def _create(
        db_name: str = "qa.db",
        api_keys: str = "secret-key-1,secret-key-2",
        enable_failure_simulation: bool = True,
        cache_enabled: bool = True,
    ) -> TestClient:
        app = create_app(
            make_settings(
                db_path=tmp_path / db_name,
                api_keys=api_keys,
                enable_failure_simulation=enable_failure_simulation,
                cache_enabled=cache_enabled,
            )
        )
        app.state.llm_service.clear_cache()
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _create

    for c in clients:
        c.__exit__(None, None, None)


def test_qa_simultaneous_requests_across_sessions(qa_client):
    client = qa_client()

    def fake_provider(*args, **kwargs):
        msg = kwargs["messages"][-1]["content"]
        return build_response(f"Echo: {msg}", 12, 4)

    def send_one(idx: int):
        return client.post(
            "/chat",
            json={"session_id": f"par-{idx}", "message": f"Question {idx}"},
        )

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=fake_provider):
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(send_one, range(6)))

    assert all(r.status_code == 200 for r in responses)
    for idx, res in enumerate(responses):
        assert res.json()["reply"] == f"Echo: Question {idx}"
        hist = client.get(f"/sessions/par-{idx}/messages")
        assert hist.status_code == 200
        assert len(hist.json()["messages"]) == 2


def test_qa_same_session_concurrent_messages_serialize_cleanly(qa_client):
    client = qa_client()
    observed_histories = []

    def fake_provider(*args, **kwargs):
        observed_histories.append([m["content"] for m in kwargs["messages"]])
        msg = kwargs["messages"][-1]["content"]
        return build_response(f"Reply({msg})", 15, 5)

    def send_same(idx: int):
        return client.post(
            "/chat",
            json={"session_id": "shared-sess", "message": f"Turn-{idx}"},
        )

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=fake_provider):
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = list(pool.map(send_same, [1, 2, 3]))

    assert all(r.status_code == 200 for r in responses)
    # Per-session lock guarantees strict causal growth: 1 message, then 3, then 5
    assert sorted(len(h) for h in observed_histories) == [1, 3, 5]

    hist = client.get("/sessions/shared-sess/messages").json()["messages"]
    assert [m["role"] for m in hist] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_qa_invalid_failure_simulation_headers_do_not_crash(qa_client):
    client = qa_client(enable_failure_simulation=True)

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        return_value=build_response("Safe response", 10, 3),
    ):
        for bad_hdr in ["bogus", "key_1=999", "=429", "key_1=abc", ",,,"]:
            res = client.post(
                "/chat",
                json={"session_id": "s-bad-hdr", "message": f"Test {bad_hdr}"},
                headers={"X-Simulate-Failure": bad_hdr},
            )
            assert res.status_code == 200
            assert res.json()["metadata"]["key_id"] == "key_1"

        # Mixed valid + invalid entry still triggers valid entry safely
        mixed = client.post(
            "/chat",
            json={"session_id": "s-mixed-hdr", "message": "Mixed"},
            headers={"X-Simulate-Failure": "invalid_entry, key_1=429, key_2=999"},
        )
        assert mixed.status_code == 200
        assert mixed.json()["metadata"]["key_id"] == "key_2"
        assert mixed.json()["metadata"]["fallback_attempts"] == 1


def test_qa_simulation_disabled_still_allows_cache_hit(qa_client):
    client = qa_client(enable_failure_simulation=False)

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        return_value=build_response("Cached when sim disabled", 9, 4),
    ):
        r1 = client.post("/chat", json={"session_id": "s-sim-off-1", "message": "Cache me"})
        r2 = client.post(
            "/chat",
            json={"session_id": "s-sim-off-2", "message": "Cache me"},
            headers={"X-Simulate-Failure": "*=429"},
        )

    assert r1.status_code == 200 and r1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r2.status_code == 200 and r2.json()["metadata"]["resolution_source"] == "LLM_CACHE"


def test_qa_cache_isolation_by_system_prompt_and_history(qa_client):
    client = qa_client()
    calls = 0

    def fake_provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        sys_msg = kwargs["messages"][0]["content"] if kwargs["messages"][0]["role"] == "system" else "none"
        hist_len = len(kwargs["messages"])
        return build_response(f"Call#{calls}|sys={sys_msg}|len={hist_len}", 20 + calls, 7)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=fake_provider):
        # System prompt isolation
        a1 = client.post(
            "/chat",
            json={"session_id": "sp-1", "message": "Summarize", "system_prompt": "Sys A"},
        ).json()
        b1 = client.post(
            "/chat",
            json={"session_id": "sp-2", "message": "Summarize", "system_prompt": "Sys B"},
        ).json()
        a2 = client.post(
            "/chat",
            json={"session_id": "sp-3", "message": "Summarize", "system_prompt": "Sys A"},
        ).json()

        # History isolation
        client.post("/chat", json={"session_id": "h-1", "message": "Topic Alpha"})
        h1_t2 = client.post("/chat", json={"session_id": "h-1", "message": "Summarize"}).json()

        client.post("/chat", json={"session_id": "h-2", "message": "Topic Beta"})
        h2_t2 = client.post("/chat", json={"session_id": "h-2", "message": "Summarize"}).json()

    assert a1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert b1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a1["reply"] != b1["reply"]

    # Repeating identical system_prompt + message across new session hits cache & keeps tokens
    assert a2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert a2["reply"] == a1["reply"]
    assert a2["metadata"]["input_tokens"] == a1["metadata"]["input_tokens"]
    assert a2["metadata"]["output_tokens"] == a1["metadata"]["output_tokens"]

    # Different prior histories MUST NOT share cache entry for identical Turn 2 message
    assert h1_t2["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert h2_t2["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert h1_t2["reply"] != h2_t2["reply"]


def test_qa_timeout_quota_and_three_key_failover(qa_client):
    client = qa_client(api_keys="k-one,k-two,k-three")
    seen_keys = []

    def provider_three(*args, **kwargs):
        key = kwargs["litellm_params"]["api_key"]
        seen_keys.append(key)
        if key == "k-one":
            raise litellm.Timeout(
                message="Request timed out",
                llm_provider="gemini",
                model="gemini/gemini-2.0-flash",
            )
        if key == "k-two":
            raise litellm.APIError(
                status_code=403,
                message="Quota exceeded for project",
                llm_provider="gemini",
                model="gemini/gemini-2.0-flash",
            )
        return build_response("Third key succeeded", 18, 4)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=provider_three):
        res = client.post("/chat", json={"session_id": "s-3keys", "message": "Test 3 keys"})

    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "Third key succeeded"
    assert body["metadata"]["key_id"] == "key_3"
    assert body["metadata"]["fallback_attempts"] == 2
    assert seen_keys == ["k-one", "k-two", "k-three"]


def test_qa_authentication_failure_stops_without_retrying_all_keys(qa_client):
    client = qa_client(api_keys="bad-key-1,valid-key-2")
    seen_keys = []

    def auth_fail(*args, **kwargs):
        seen_keys.append(kwargs["litellm_params"]["api_key"])
        raise litellm.AuthenticationError(
            message="Invalid API key bad-key-1",
            llm_provider="gemini",
            model="gemini/gemini-2.0-flash",
        )

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=auth_fail):
        res = client.post("/chat", json={"session_id": "s-auth", "message": "Hello"})

    assert res.status_code == 401
    assert "detail" in res.json()
    assert "bad-key-1" not in res.text
    assert seen_keys == ["bad-key-1"]


def test_qa_empty_and_malformed_provider_responses_failover_and_503(qa_client):
    client = qa_client()

    # Empty on key_1 -> valid on key_2
    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        side_effect=[build_response("   ", 5, 0), build_response("Recovered reply", 11, 3)],
    ):
        r_empty = client.post("/chat", json={"session_id": "s-empty-rep", "message": "Test empty"})
    assert r_empty.status_code == 200
    assert r_empty.json()["metadata"]["key_id"] == "key_2"
    assert r_empty.json()["metadata"]["fallback_attempts"] == 1

    # Malformed responses on both keys -> clean 503 JSON, no crash
    malformed_1 = {"choices": [{"message": {"content": 12345}}]}
    malformed_2 = None
    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        side_effect=[malformed_1, malformed_2],
    ):
        r_mal = client.post("/chat", json={"session_id": "s-malformed", "message": "Test malformed"})
    assert r_mal.status_code == 503
    assert r_mal.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-malformed/messages").status_code == 404


def test_qa_sqlite_transaction_rollback_on_write_failure(tmp_path: Path):
    db = Database(str(tmp_path / "rollback.db"))
    db.init_db()

    class BrokenInsertConn:
        def __init__(self, real_conn):
            self._real = real_conn
            self._calls = 0

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._real.__exit__(exc_type, exc_val, exc_tb)

        def execute(self, sql, params=()):
            self._calls += 1
            if self._calls == 3:
                raise RuntimeError("Simulated disk full during assistant insert")
            return self._real.execute(sql, params)

        def close(self):
            self._real.close()

    real_conn = db._create_connection()
    with patch.object(db, "_get_connection", return_value=(BrokenInsertConn(real_conn), True)):
        with pytest.raises(RuntimeError, match="Simulated disk full"):
            db.save_turn("s-rollback", "sys", "Should roll back", "Assistant", {"k": "v"})

    assert db.get_session("s-rollback") is None
    assert db.get_messages("s-rollback") == []


def test_qa_cors_preflight_trailing_slash_and_malformed_json(qa_client):
    client = qa_client()

    # Trailing slash in ALLOWED_ORIGINS ("https://app.example.com/") normalized cleanly
    preflight = client.options(
        "/chat",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Simulate-Failure",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "https://app.example.com"

    # Malformed JSON returns 422 JSON, never HTML
    bad_json = client.post(
        "/chat",
        content="{not-valid-json",
        headers={"Content-Type": "application/json"},
    )
    assert bad_json.status_code == 422
    assert "detail" in bad_json.json()


def test_qa_database_url_docker_posix_parsing():
    s = Settings(DATABASE_URL="sqlite:////data/app.db")
    assert Path(s.sqlite_path).as_posix() == "/data/app.db"
