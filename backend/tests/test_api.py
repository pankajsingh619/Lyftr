from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(
    db_path: Path,
    enable_failure_simulation: bool = True,
    cache_enabled: bool = True,
    api_keys: str = "secret-key-1,secret-key-2",
    allowed_origins: str = "http://localhost:3000",
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


def build_model_response(content: str, prompt_tokens: int, completion_tokens: int, include_usage: bool = True):
    kwargs = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "model": "gemini/gemini-2.0-flash",
    }
    if include_usage:
        kwargs["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    else:
        kwargs["usage"] = None
    return litellm.ModelResponse(**kwargs)


@pytest.fixture
def app_factory(tmp_path: Path):
    clients: list[TestClient] = []

    def _create(
        db_name: str = "test.db",
        enable_failure_simulation: bool = True,
        cache_enabled: bool = True,
        api_keys: str = "secret-key-1,secret-key-2",
    ) -> TestClient:
        db_path = tmp_path / db_name
        settings = make_settings(
            db_path=db_path,
            enable_failure_simulation=enable_failure_simulation,
            cache_enabled=cache_enabled,
            api_keys=api_keys,
        )
        app = create_app(settings)
        app.state.llm_service.clear_cache()
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _create

    for client in clients:
        client.__exit__(None, None, None)


def test_01_health_endpoint(app_factory):
    client = app_factory()
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "keys_configured": 2,
        "cache_enabled": True,
    }


def test_01b_health_returns_503_when_no_keys(app_factory):
    client = app_factory(api_keys="")
    res = client.get("/health")
    assert res.status_code == 503
    assert "detail" in res.json()


def test_02_successful_chat_exact_schema(app_factory):
    client = app_factory()

    def fake_provider(*args, **kwargs):
        assert kwargs["litellm_params"]["api_key"] == "secret-key-1"
        return build_model_response("Paris is the capital of France.", 14, 7)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=fake_provider):
        res = client.post(
            "/chat",
            json={"session_id": "s-101", "message": "What is the capital of France?"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "s-101"
    assert body["reply"] == "Paris is the capital of France."
    meta = body["metadata"]
    assert set(meta.keys()) == {
        "resolution_source",
        "model",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "key_id",
        "fallback_attempts",
    }
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.0-flash"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    assert meta["input_tokens"] == 14
    assert meta["output_tokens"] == 7
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert "secret-key-1" not in res.text
    assert "secret-key-2" not in res.text


def test_03_missing_or_invalid_session_id_returns_422(app_factory):
    client = app_factory()
    for bad_payload in [
        {"message": "Hello"},
        {"session_id": "", "message": "Hello"},
        {"session_id": "   ", "message": "Hello"},
        {"session_id": "x" * 129, "message": "Hello"},
    ]:
        res = client.post("/chat", json=bad_payload)
        assert res.status_code == 422
        assert "detail" in res.json()


def test_04_empty_message_returns_422(app_factory):
    client = app_factory()
    for bad_msg in ["", "   \n\t  "]:
        res = client.post("/chat", json={"session_id": "s-empty", "message": bad_msg})
        assert res.status_code == 422
        assert "detail" in res.json()


def test_05_message_length_bounds(app_factory):
    client = app_factory()
    too_long = client.post(
        "/chat",
        json={"session_id": "s-long", "message": "a" * 4001},
    )
    assert too_long.status_code == 422
    assert "detail" in too_long.json()

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        return_value=build_model_response("Accepted", 100, 2),
    ):
        exact_max = client.post(
            "/chat",
            json={"session_id": "s-long", "message": "  " + ("a" * 4000) + "  "},
        )
    assert exact_max.status_code == 200


def test_06_multi_turn_conversation_and_system_prompt(app_factory):
    client = app_factory()
    seen_messages = []

    def fake_provider(*args, **kwargs):
        seen_messages.append(list(kwargs["messages"]))
        turn = len(seen_messages)
        return build_model_response(f"Reply {turn}", 10 * turn, 4)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=fake_provider):
        r1 = client.post(
            "/chat",
            json={
                "session_id": "s-multi",
                "message": "My name is Alice.",
                "system_prompt": "Be concise.",
            },
        )
        r2 = client.post(
            "/chat",
            json={"session_id": "s-multi", "message": "What is my name?"},
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert seen_messages[0] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "My name is Alice."},
    ]
    assert seen_messages[1] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "My name is Alice."},
        {"role": "assistant", "content": "Reply 1"},
        {"role": "user", "content": "What is my name?"},
    ]


def test_07_session_isolation(app_factory):
    client = app_factory()
    observed = []

    def fake_provider(*args, **kwargs):
        observed.append(list(kwargs["messages"]))
        return build_model_response(f"Ans {len(observed)}", 8, 3)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=fake_provider):
        client.post("/chat", json={"session_id": "s-alpha", "message": "Alpha secret"})
        client.post("/chat", json={"session_id": "s-beta", "message": "Beta question"})

    assert observed[1] == [{"role": "user", "content": "Beta question"}]


def test_08_history_endpoint_oldest_first_no_system_prompt(app_factory):
    client = app_factory()

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        side_effect=[
            build_model_response("First reply", 11, 5),
            build_model_response("Second reply", 22, 6),
        ],
    ):
        client.post(
            "/chat",
            json={
                "session_id": "s-hist",
                "message": "First question",
                "system_prompt": "Hidden system instructions",
            },
        )
        client.post(
            "/chat",
            json={"session_id": "s-hist", "message": "Second question"},
        )

    hist = client.get("/sessions/s-hist/messages")
    assert hist.status_code == 200
    payload = hist.json()
    assert payload["session_id"] == "s-hist"
    msgs = payload["messages"]
    assert len(msgs) == 4
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert all(m["role"] != "system" for m in msgs)
    assert msgs[0] == {"role": "user", "content": "First question"}
    assert msgs[1]["content"] == "First reply"
    assert msgs[1]["metadata"]["input_tokens"] == 11
    assert msgs[1]["metadata"]["output_tokens"] == 5
    assert msgs[3]["content"] == "Second reply"


def test_09_unknown_session_returns_404(app_factory):
    client = app_factory()
    res = client.get("/sessions/does-not-exist/messages")
    assert res.status_code == 404
    assert res.json() == {"detail": "session not found"}


def test_10_11_12_caching_across_sessions_isolation_and_metadata(app_factory):
    client = app_factory()
    call_count = 0

    def slow_provider(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        time.sleep(0.25)
        user_text = kwargs["messages"][-1]["content"]
        return build_model_response(f"Answer for: {user_text}", 19, 8)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=slow_provider):
        first = client.post(
            "/chat",
            json={"session_id": "cache-s1", "message": "Explain caching briefly."},
        )
        second = client.post(
            "/chat",
            json={"session_id": "cache-s2", "message": "Explain caching briefly."},
        )
        different = client.post(
            "/chat",
            json={"session_id": "cache-s3", "message": "Explain failover briefly."},
        )
        diff_sys = client.post(
            "/chat",
            json={
                "session_id": "cache-s4",
                "message": "Explain caching briefly.",
                "system_prompt": "Respond as a pirate.",
            },
        )

    assert call_count == 3  # second hit LiteLLM cache without calling provider

    first_json = first.json()
    second_json = second.json()
    assert first_json["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert first_json["metadata"]["key_id"] == "key_1"

    assert second_json["reply"] == first_json["reply"]
    assert second_json["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second_json["metadata"]["key_id"] is None
    assert second_json["metadata"]["fallback_attempts"] == 0
    assert second_json["metadata"]["input_tokens"] == 19
    assert second_json["metadata"]["output_tokens"] == 8
    assert second_json["metadata"]["latency_ms"] < first_json["metadata"]["latency_ms"]

    assert different.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert diff_sys.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_13_failover_key1_to_key2_simulated_and_real_and_cache_bypass(app_factory):
    client = app_factory(enable_failure_simulation=True)

    # First populate cache with the same prompt to verify simulation is NOT hidden by cache
    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        return_value=build_model_response("Cached answer", 10, 4),
    ):
        warm = client.post("/chat", json={"session_id": "s-warm", "message": "Capital of Japan?"})
        assert warm.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    called_keys = []

    def provider_key2(*args, **kwargs):
        called_keys.append(kwargs["litellm_params"]["api_key"])
        return build_model_response("Tokyo", 15, 3)

    # TEST A: key_1=429
    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=provider_key2):
        res_429 = client.post(
            "/chat",
            json={"session_id": "s-fail-429", "message": "Capital of Japan?"},
            headers={"X-Simulate-Failure": "key_1=429"},
        )
    assert res_429.status_code == 200
    assert res_429.json()["reply"] == "Tokyo"
    assert res_429.json()["metadata"]["key_id"] == "key_2"
    assert res_429.json()["metadata"]["fallback_attempts"] == 1
    assert res_429.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    # TEST B: key_1=500
    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=provider_key2):
        res_500 = client.post(
            "/chat",
            json={"session_id": "s-fail-500", "message": "Capital of Japan?"},
            headers={"X-Simulate-Failure": "key_1=500"},
        )
    assert res_500.status_code == 200
    assert res_500.json()["metadata"]["key_id"] == "key_2"
    assert res_500.json()["metadata"]["fallback_attempts"] == 1
    assert called_keys == ["secret-key-2", "secret-key-2"]

    # Real provider exception on key_1 -> fails over to key_2
    real_calls = []

    def real_fail_then_succeed(*args, **kwargs):
        key = kwargs["litellm_params"]["api_key"]
        real_calls.append(key)
        if key == "secret-key-1":
            raise litellm.RateLimitError(
                message="429 Resource Exhausted",
                llm_provider="gemini",
                model="gemini/gemini-2.0-flash",
            )
        return build_model_response("Real failover works", 12, 5)

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=real_fail_then_succeed):
        res_real = client.post(
            "/chat",
            json={"session_id": "s-real-fail", "message": "Unique real failover question"},
        )
    assert res_real.status_code == 200
    assert res_real.json()["metadata"]["key_id"] == "key_2"
    assert res_real.json()["metadata"]["fallback_attempts"] == 1
    assert real_calls == ["secret-key-1", "secret-key-2"]


def test_14_15_16_all_keys_fail_and_history_unmodified(app_factory):
    client = app_factory(enable_failure_simulation=True)

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        return_value=build_model_response("Hello back", 7, 2),
    ):
        ok = client.post("/chat", json={"session_id": "s-503", "message": "Hello"})
        assert ok.status_code == 200

    # TEST C: key_1=429,key_2=500 -> 503
    res_both = client.post(
        "/chat",
        json={"session_id": "s-503", "message": "Should fail both"},
        headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
    )
    assert res_both.status_code == 503
    assert res_both.json() == {"detail": "all providers unavailable"}

    # TEST D: *=429 -> 503 (even on cached prompt!)
    res_wild = client.post(
        "/chat",
        json={"session_id": "s-503-new", "message": "Hello"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert res_wild.status_code == 503
    assert res_wild.json() == {"detail": "all providers unavailable"}

    # Failed 422 request must also not modify history
    res_422 = client.post("/chat", json={"session_id": "s-503", "message": "   "})
    assert res_422.status_code == 422

    # Verify history integrity
    hist_existing = client.get("/sessions/s-503/messages")
    assert hist_existing.status_code == 200
    assert len(hist_existing.json()["messages"]) == 2

    hist_new = client.get("/sessions/s-503-new/messages")
    assert hist_new.status_code == 404


def test_17_per_request_tokens_and_tokenizer_fallback(app_factory):
    client = app_factory()

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        side_effect=[
            build_model_response("A1", 10, 3),
            build_model_response("A2", 25, 4),
            build_model_response("Fallback estimated reply", 0, 0, include_usage=False),
        ],
    ):
        t1 = client.post("/chat", json={"session_id": "s-tok", "message": "Turn 1"}).json()
        t2 = client.post("/chat", json={"session_id": "s-tok", "message": "Turn 2"}).json()
        t3 = client.post(
            "/chat",
            json={"session_id": "s-tok-est", "message": "Count tokens via fallback please"},
        ).json()

    # Turn 2 reports turn 2's prompt tokens (25), not cumulative 10+25
    assert t1["metadata"]["input_tokens"] == 10
    assert t2["metadata"]["input_tokens"] == 25
    assert t3["metadata"]["input_tokens"] > 0
    assert t3["metadata"]["output_tokens"] > 0


def test_18_sqlite_persistence_across_app_restart(tmp_path: Path):
    db_file = tmp_path / "persistent.db"

    app1 = create_app(make_settings(db_path=db_file))
    app1.state.llm_service.clear_cache()
    with TestClient(app1) as c1:
        with patch.object(
            litellm.vertex_chat_completion,
            "completion",
            return_value=build_model_response("Nice to meet you, Bob.", 12, 6),
        ):
            r1 = c1.post("/chat", json={"session_id": "persist-1", "message": "Hi, I am Bob."})
            assert r1.status_code == 200

    # Simulate container/app restart with a brand-new FastAPI app pointing to same SQLite DB
    seen = []

    def turn2_provider(*args, **kwargs):
        seen.append(list(kwargs["messages"]))
        return build_model_response("Your name is Bob.", 28, 5)

    app2 = create_app(make_settings(db_path=db_file))
    with TestClient(app2) as c2:
        hist = c2.get("/sessions/persist-1/messages")
        assert hist.status_code == 200
        assert len(hist.json()["messages"]) == 2

        with patch.object(litellm.vertex_chat_completion, "completion", side_effect=turn2_provider):
            r2 = c2.post("/chat", json={"session_id": "persist-1", "message": "Who am I?"})
            assert r2.status_code == 200

    assert seen[0] == [
        {"role": "user", "content": "Hi, I am Bob."},
        {"role": "assistant", "content": "Nice to meet you, Bob."},
        {"role": "user", "content": "Who am I?"},
    ]


def test_19_cors_behavior(app_factory):
    client = app_factory()
    allowed = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Simulate-Failure",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    disallowed = client.get("/health", headers={"Origin": "https://untrusted.example"})
    assert disallowed.status_code == 200
    assert "access-control-allow-origin" not in disallowed.headers


def test_20_failure_simulation_disabled_ignores_header(app_factory):
    client = app_factory(enable_failure_simulation=False)

    with patch.object(
        litellm.vertex_chat_completion,
        "completion",
        return_value=build_model_response("Normal response", 9, 3),
    ):
        res = client.post(
            "/chat",
            json={"session_id": "s-nosim", "message": "Test disabled sim"},
            headers={"X-Simulate-Failure": "*=429"},
        )
    assert res.status_code == 200
    assert res.json()["metadata"]["key_id"] == "key_1"
    assert res.json()["metadata"]["fallback_attempts"] == 0


def test_21_non_retryable_client_error_does_not_failover(app_factory):
    client = app_factory()
    calls = []

    def bad_req(*args, **kwargs):
        calls.append(kwargs["litellm_params"]["api_key"])
        raise litellm.BadRequestError(
            message="Bad request",
            llm_provider="gemini",
            model="gemini/gemini-2.0-flash",
        )

    with patch.object(litellm.vertex_chat_completion, "completion", side_effect=bad_req):
        res = client.post("/chat", json={"session_id": "s-bad", "message": "Bad input"})

    assert res.status_code == 400
    assert "detail" in res.json()
    assert calls == ["secret-key-1"]
