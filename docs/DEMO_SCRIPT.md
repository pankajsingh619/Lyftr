# 2–3 Minute Demo Script with Voiceover

**Target Duration:** ~2 minutes 30 seconds  
**Prerequisites:** Backend and Frontend running locally (`http://localhost:8000` & `http://localhost:3000`) or via deployed URLs, with at least two valid LLM API keys configured in `LLM_API_KEYS` and `ENABLE_FAILURE_SIMULATION=true`.

---

## Scene 1 — Health Check & Application Overview (0:00 – 0:25)

**Action:**  
Open a terminal and run `GET /health`, then switch to the browser showing the live React frontend.

```bash
curl -s http://localhost:8000/health | jq .
```

**Expected Output:**
```json
{
  "status": "ok",
  "keys_configured": 2,
  "cache_enabled": true
}
```

**Voiceover:**  
> "Hi, this is my submission for the Lyftr AI Full-Stack Assignment: a resilient LLM chatbot built with React, FastAPI, LiteLLM, and SQLite. First, hitting `/health` confirms our SQLite database is connected, two API keys are loaded in the key pool, and LiteLLM response caching is enabled. In the browser, each page load automatically generates a fresh client-side session ID."

---

## Scene 2 — First Message & `LIVE_INFERENCE` Metadata (0:25 – 0:50)

**Action:**  
In the chat input (`data-testid="chat-input"`), type `What is the capital of France?` and press Enter. Point out the metadata bar beneath the assistant reply.

**Voiceover:**  
> "I'll send a first question: 'What is the capital of France?'. Below the reply, we see the exact per-request metadata returned by the backend: `LIVE_INFERENCE` as the resolution source, the LiteLLM model name, server-measured latency in milliseconds, per-request input and output tokens, and `key_1` with `0` fallback attempts."

---

## Scene 3 — Cross-Session Cache Hit (`LLM_CACHE`) (0:50 – 1:15)

**Action:**  
Click **+ New Chat** in the sidebar to generate a brand-new `session_id`. Send the exact same prompt: `What is the capital of France?`.

**Voiceover:**  
> "Now I'll start a completely new session by clicking New Chat — notice the session ID in the header changed. When I send the exact same first message, LiteLLM's built-in cache keys on the model and prompt list rather than the session ID. The reply returns near-instantly with `LLM_CACHE`, `key_id=null`, `0` fallbacks, and the original token counts preserved."

---

## Scene 4 — Multi-Turn Memory & Per-Request Tokens (1:15 – 1:40)

**Action:**  
In the same session, send a follow-up message: `What river flows through that city?`.

**Voiceover:**  
> "Because the frontend sends only the newest message while FastAPI reconstructs conversation history from SQLite, the bot remembers that 'that city' refers to Paris and answers the Seine. Notice the input token count reflects this request's full prompt context rather than a cumulative conversation total."

---

## Scene 5 — Key Failover (`key_1=429` -> `key_2`) & `503` Handling (1:40 – 2:20)

**Action:**  
1. Open **Developer Mode (Failover Sim)** in the sidebar (or run the `curl` command in terminal), select `key_1=429`, and send `Name two oceans on Earth.`
2. Then select `*=429` (or run `curl` with `X-Simulate-Failure: key_1=429,key_2=500`) and send `This should fail cleanly.`

```bash
# Key 1 fails with 429 -> automatic failover to Key 2
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id":"demo-failover","message":"Name two oceans on Earth."}' | jq .

# All keys fail -> HTTP 503 JSON, nothing written to history
curl -i -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id":"demo-failover","message":"Should fail"}'
```

**Voiceover:**  
> "Next, let's test resilience using `X-Simulate-Failure`. When I simulate HTTP 429 on `key_1`, the backend bypasses the cache so the failure cannot be masked, catches the rate limit, and automatically retries with `key_2` — returning a real LLM response with `key_id: key_2` and `fallback_attempts: 1`. When I simulate `*=429` so all keys fail, the backend returns HTTP 503 `{"detail": "all providers unavailable"}` and the UI displays a clean error banner without crashing or corrupting session history."

---

## Scene 6 — SQLite History Endpoint (2:20 – 2:40)

**Action:**  
Fetch `GET /sessions/{session_id}/messages` in the terminal to show ordered history and confirm the failed 503 message was not stored.

```bash
curl -s http://localhost:8000/sessions/demo-failover/messages | jq .
```

**Voiceover:**  
> "Finally, querying `/sessions/demo-failover/messages` confirms our SQLite history returns messages oldest-first with assistant metadata intact, no system prompt leaked, and no trace of the failed 503 request. Thanks for watching!"
