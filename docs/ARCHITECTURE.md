# Architecture — Lyftr AI LLM Chatbot

## 1. System Overview

This application is a fault-tolerant, multi-turn AI chatbot built with a **React** frontend, a **FastAPI** backend, **LiteLLM** as the LLM gateway (for model invocation, built-in response caching, and token extraction), and **SQLite** for persistent session and message storage.

```
+---------------------------+          HTTP / JSON           +--------------------------------------+
|   React Frontend (SPA)    | -----------------------------> |         FastAPI Backend              |
|  - Session generator     |   POST /chat                   |  - CORS & JSON Error Middleware      |
|  - Chat UI + Metadata    |   GET  /sessions/{id}/messages |  - Request Validation (Pydantic)     |
|  - Failover Sim Drawer   |   GET  /health                 |  - X-Simulate-Failure Parser         |
+---------------------------+                                +------------------+-------------------+
                                                                                |
                                                +-------------------------------+-------------------------------+
                                                |                                                               |
                                                v                                                               v
                                  +---------------------------+                                   +---------------------------+
                                  |     SQLite (/data/app.db) |                                   |   LiteLLM Gateway Service |
                                  |  - sessions table         |                                   |  - Built-in Cache (local) |
                                  |  - messages table (JSON)  |                                   |  - Key Pool (key_1..N)    |
                                  +---------------------------+                                   |  - Auto Failover Loop     |
                                                                                                  +-------------+-------------+
                                                                                                                |
                                                                                                                v
                                                                                                  +---------------------------+
                                                                                                  |  External LLM Provider(s) |
                                                                                                  |  (e.g., Gemini / OpenAI)  |
                                                                                                  +---------------------------+
```

## 2. Request Lifecycle (`POST /chat`)

1. **Validation & Context Assembly**:
   - FastAPI validates `session_id` (1–128 chars), `message` (1–4000 chars after `.strip()`), and optional `system_prompt` via Pydantic schemas (invalid payloads return HTTP 422 JSON).
   - Start monotonic server-side timer (`time.perf_counter()`).
   - Parse `X-Simulate-Failure` header if `ENABLE_FAILURE_SIMULATION=true`.
   - Load existing session (and stored `system_prompt`, if any) and prior conversation messages from SQLite (`ORDER BY id ASC`).
   - Build the full `messages` array for LiteLLM: `[system_message (if set), ...history, new_user_message]`. The new user message is persisted only after a successful LLM response so failed requests never pollute history.

2. **Cache Check & Provider Failover (`LiteLLMService`)**:
   - **Cache Key Isolation**: LiteLLM's built-in cache keys on `(model, messages, ...)` independent of `session_id`. Identical first messages across different sessions hit the same cache entry, while differing system prompts or multi-turn histories remain isolated.
   - **Simulation Bypass**: If `X-Simulate-Failure` targets one or more keys (`ENABLE_FAILURE_SIMULATION=true`), cache lookup is bypassed (`no-cache`) so simulated failures cannot be masked by a prior cache hit.
   - **Key Pool Execution**:
     - Configured keys from `LLM_API_KEYS` are mapped deterministically to `key_1`, `key_2`, ..., `key_N`.
     - If no simulated failure applies and a cache hit occurs via LiteLLM's built-in cache (`_hidden_params.get("cache_hit")`), return immediately with `resolution_source="LLM_CACHE"`, `key_id=None`, `fallback_attempts=0`, and the cached response's original `input_tokens` and `output_tokens`.
     - On cache miss (or simulation), iterate through keys `key_1 .. key_N`:
       - If the current `key_id` is targeted by `X-Simulate-Failure` (status `429`, `500`, `502`, or `503`), raise the corresponding simulated LiteLLM error without contacting the provider, increment `fallback_attempts`, and advance to the next key.
       - Otherwise, invoke `litellm.completion(...)` with that key.
       - On transient/failover errors (`429`, quota exhaustion, `500`, `502`, `503`, `504`, connection/timeout), increment `fallback_attempts` and advance to the next key.
       - On non-retryable client errors (`400` bad request), abort immediately.
       - If all keys fail, raise `AllProvidersUnavailableError` -> HTTP `503 {"detail": "all providers unavailable"}`.

3. **Persistence & Response**:
   - After obtaining a valid non-empty assistant reply, upsert the session in `sessions` and insert the user + assistant messages (with metadata JSON and ISO-8601 UTC timestamp) into `messages` in one SQLite transaction.
   - Measure elapsed time in integer milliseconds (`latency_ms`) and return the exact `ChatResponse` contract.

## 3. Data Model (SQLite)

- **`sessions`**: `session_id TEXT PRIMARY KEY`, `system_prompt TEXT`, `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`
- **`messages`**: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `session_id TEXT NOT NULL`, `role TEXT NOT NULL`, `content TEXT NOT NULL`, `metadata TEXT`, `created_at TEXT NOT NULL`
- **Index**: `idx_messages_session_id_id` on `messages(session_id, id)`
