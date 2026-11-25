# Lyftr AI — LLM Chatbot with Key Failover and Response Caching

A full-stack, multi-turn AI chatbot built with **React (Vite)**, **FastAPI**, **LiteLLM**, and **SQLite**, featuring automatic API key failover, built-in response caching, per-request token tracking, and on-demand failure simulation.

---

## 1. Live URLs

- **GitHub Repository URL:** https://github.com/pankajsingh619/Lyftr
- **Live Frontend URL:** *Not yet deployed publicly* (ready-to-deploy [frontend/vercel.json](frontend/vercel.json) is included; verified locally via `http://127.0.0.1:3000`).
- **Live Backend URL:** *Not yet deployed publicly* (ready-to-deploy [render.yaml](render.yaml) with persistent `/data` disk configuration is included; verified locally via `http://127.0.0.1:8000`).

### Exact Public Deployment Instructions

1. **Push updates to GitHub (`https://github.com/pankajsingh619/Lyftr`)**:
   ```bash
   git push -u origin main
   ```
2. **Deploy Backend on Render (with Persistent Disk for SQLite)**:
   - In Render Dashboard, select **New → Blueprint** (or **New → Web Service** using `backend/Dockerfile`) and connect your GitHub repo (`render.yaml` is already configured).
   - Attach a **1 GB Persistent Disk** mounted at `/data`.
   - Set environment variables in Render:
     - `LLM_API_KEYS=<your_key_1>,<your_key_2>`
     - `LLM_MODEL=openrouter/openrouter/free` (or your supported LiteLLM model)
     - `DATABASE_URL=sqlite:////data/app.db`
     - `ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app`
     - `ENABLE_FAILURE_SIMULATION=false` *(keep `false` in production; set `true` only during controlled staging/demo failover tests)*
     - `CACHE_ENABLED=true`
     - `CACHE_TYPE=local`
   - Verify `https://<your-backend>.onrender.com/health` returns HTTP `200`.
3. **Deploy Frontend on Vercel**:
   - Import the repo in Vercel with **Root Directory** set to `frontend` (Framework: Vite).
   - Add environment variable: `VITE_API_BASE_URL=https://<your-backend>.onrender.com`.
   - Deploy and copy the public Vercel domain into Render's `ALLOWED_ORIGINS` (redeploy backend if updated).

---

## 2. Run locally: with Docker and without

### Prerequisites

- At least **two** real LLM API keys (e.g., Google Gemini, OpenAI, or Groq) for live inference and failover.
- Copy `.env.example` to `.env` at the repository root and set `LLM_API_KEYS`:
  ```bash
  cp .env.example .env
  ```

### Option A: With Docker (Recommended)

Requires Docker and Docker Compose (`make` on macOS/Linux, or `scripts/docker.ps1` on Windows PowerShell):

```bash
make up
```

Windows PowerShell alternative (when GNU `make` is unavailable):

```powershell
.\scripts\docker.ps1 up
.\scripts\docker.ps1 verify
.\scripts\docker.ps1 down
```

Or directly via Docker Compose:

```bash
docker compose up --build -d
```

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- SQLite DB persists on the named Docker volume `lyftr_sqlite_data` mounted at `/data/app.db`.

Stop the stack (preserving the `/data` volume):

```bash
make down
```

### Option B: Without Docker (Local Python + Node.js)

**Quick Start on Windows PowerShell (Recommended):**

```powershell
# 1. Optional: copy .env.example to .env and add your real LLM_API_KEYS
copy .env.example .env

# 2. Start both FastAPI (127.0.0.1:8000) and Vite React UI (127.0.0.1:3000)
.\scripts\start-local.ps1

# 3. Verify health, UI, SQLite, 404/422/503, and test IDs
.\scripts\verify-local.ps1

# 4. Stop only the servers started by this project
.\scripts\stop-local.ps1
```

Server logs are written to `logs/backend.log` and `logs/frontend.log`.

**Manual Startup:**

**1. Start Backend (`http://127.0.0.1:8000`)**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

*(Note: `backend/app/config.py` automatically loads `.env` from both the repository root and `backend/`. Without `LLM_API_KEYS`, the server still starts and returns HTTP `503 {"detail": "no LLM keys configured"}` on `/health` until keys are supplied.)*

**2. Start Frontend (`http://127.0.0.1:3000`)**

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 3000
```

*(Development automatically uses `frontend/.env.development` with `VITE_API_BASE_URL=http://127.0.0.1:8000`. Production `npm run build` ignores `.env.development` so no localhost URL is baked into production bundles.)*

**3. Run Automated Backend Tests**

```bash
cd backend
pytest -v
```

---

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key Fallback (`backend/app/services/litellm_service.py`)

- **Ordered Key Pool**: `LLM_API_KEYS` is parsed in order into `key_1`, `key_2`, ..., `key_N` (optionally paired with per-key models via `LLM_MODELS`, defaulting to `LLM_MODEL`). Actual key values are never returned in API payloads, persisted in SQLite, or logged.
- **Deterministic Failover**: `LiteLLMService.complete_chat` invokes `litellm.completion(..., num_retries=0)` so LiteLLM does not silently burn retries on a dead key before switching. On transient/quota errors (`429`, `RateLimitError`, quota exhaustion markers, `500`, `502`, `503`, `504`, `Timeout`, `APIConnectionError`), the gateway increments `fallback_attempts` and immediately attempts the next key in the pool.
- **Fail-Fast Client Errors & Clean 503**: Non-retryable `400 BadRequestError` / `401 AuthenticationError` errors do not loop indefinitely across keys. If every configured key fails with transient/quota errors, the backend raises `AllProvidersUnavailableError`, returning HTTP `503 {"detail": "all providers unavailable"}` without modifying conversation history.
- **Request-Scoped Simulation**: When `ENABLE_FAILURE_SIMULATION=true`, the `X-Simulate-Failure` header (`key_1=429`, `key_1=429,key_2=500`, `*=429`) triggers real LiteLLM exception objects for only that single request without disabling keys globally.

### Response Caching (`litellm.Cache`)

- **LiteLLM Built-in Cache**: Enabled via `litellm.cache = Cache(type="local")` (in-memory; the supported built-in cache in `litellm 1.111.0`, since `disk` was removed upstream). `orjson` is included in `requirements.txt` so LiteLLM's cache-hit hydration path executes cleanly.
- **Cross-Session Key Isolation**: `session_id` and `api_key` are excluded from LiteLLM's cache key, while `model` and the complete `messages` array (`[system_prompt, ...history, new_user_message]`) are hashed. Consequently, identical first messages across two separate sessions hit `LLM_CACHE`, while differing system prompts or multi-turn histories remain isolated.
- **Simulation Bypass**: Whenever `X-Simulate-Failure` is active (`ENABLE_FAILURE_SIMULATION=true`), the request passes `caching=False, cache={"no-cache": True, "no-store": True}` so an existing cache entry can never hide a simulated provider failure.
- **Accurate Cache Metadata**: On `_hidden_params["cache_hit"] is True`, the API returns `resolution_source="LLM_CACHE"`, `key_id=null`, `fallback_attempts=0`, the identical cached `reply`, the original cached `input_tokens`/`output_tokens`, and independently measured server `latency_ms`.

### SQLite Session Storage (`backend/app/database.py`)

- **SQLite Exclusively**: Uses Python's standard `sqlite3` driver with WAL mode, `busy_timeout=5000`, and thread-safe locking. Tables (`sessions` and `messages`) plus index `idx_messages_session_id_id` are auto-created on startup via FastAPI lifespan.
- **Atomic Turn Persistence**: `save_turn()` executes an atomic transaction upserting `sessions` (storing the session's `system_prompt`) and inserting both the `user` and `assistant` rows (with ISO-8601 UTC timestamps and JSON-serialized assistant metadata) **only after** a successful LLM response. Failed `422` and `503` requests never pollute SQLite history.
- **Exact Contract**: `GET /sessions/{session_id}/messages` queries `ORDER BY id ASC`, excludes the `system_prompt`, omits `metadata` on user items, preserves `metadata` on assistant items, and returns HTTP `404 {"detail": "session not found"}` for unknown sessions.

---

## 4. Verification: how to see failover, cache hits and per-message token usage

### Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_API_KEYS` | `""` | Comma-separated provider keys mapped to `key_1`, `key_2`, ... |
| `LLM_MODEL` | `gemini/gemini-2.0-flash` | Default LiteLLM model string |
| `LLM_MODELS` | `""` | Optional comma-separated per-key models |
| `DEFAULT_SYSTEM_PROMPT` | `None` | Optional fallback system prompt |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLite path (`sqlite:////data/app.db` in Docker) |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `false` (`true` in `.env.example` & Docker) | Enables `X-Simulate-Failure` header |
| `CACHE_ENABLED` | `true` | Enables LiteLLM built-in cache |
| `CACHE_TYPE` | `local` | `local` (in-memory built-in LiteLLM cache) |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` (dev) | Frontend backend base URL (`.env.development` in dev; build arg in prod) |
| `VITE_ENABLE_FAILURE_SIMULATION` | `true` (dev/Docker), `false` (prod) | Controls visibility of `X-Simulate-Failure` UI in Developer Inspector |

### API Verification Examples

1. **Health check**:
   ```bash
   curl -s http://localhost:8000/health
   # {"status":"ok","keys_configured":2,"cache_enabled":true}
   ```

2. **Live inference + per-request token tracking**:
   ```bash
   curl -s -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id":"verify-1","message":"What is the capital of France?"}'
   # resolution_source: "LIVE_INFERENCE", key_id: "key_1", fallback_attempts: 0
   ```

3. **Cross-session cache hit**:
   ```bash
   curl -s -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id":"verify-2","message":"What is the capital of France?"}'
   # resolution_source: "LLM_CACHE", key_id: null, fallback_attempts: 0, lower latency_ms, identical reply & tokens
   ```

4. **Multi-turn memory & per-request tokens**:
   ```bash
   curl -s -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id":"verify-1","message":"What river runs through it?"}'
   # input_tokens reflects turn 2's full context (history + new message), not a cumulative sum
   ```

5. **Key failover (`key_1` fails -> `key_2` answers) & all-keys 503**:
   ```bash
   # Single-key failure -> HTTP 200 with key_id="key_2", fallback_attempts=1
   curl -s -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: key_1=429" \
     -d '{"session_id":"verify-fail","message":"What is the capital of France?"}'

   # All keys fail -> HTTP 503 {"detail":"all providers unavailable"}
   curl -i -s -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: *=429" \
     -d '{"session_id":"verify-fail","message":"Should fail"}'
   ```

6. **Session history check (oldest-first, failed 503 excluded)**:
   ```bash
   curl -s http://localhost:8000/sessions/verify-fail/messages
   ```

7. **Automated real-provider acceptance script** (once real keys are configured in `.env`):
   ```bash
   python scripts/verify_live_provider.py --base-url http://127.0.0.1:8000
   ```

Additional documentation:
- Architecture & request lifecycle: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- CI/CD & GitHub branch protection: [docs/CI_CD.md](docs/CI_CD.md)
- 2–3 minute demo voiceover script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- Independent QA & readiness audit: [FINAL_AUDIT.md](FINAL_AUDIT.md)

---

## 5. Setup Used: your editor and AI tools

- **Editor / Environment:** Antigravity AI IDE on Windows 11 (Python 3.14.6, Node.js 24.18.0)
- **AI Assistant:** Antigravity coding agent used for architecture design, FastAPI/LiteLLM/React implementation, automated pytest authoring, and verification.

---

## 6. Bonus features (if any): what you added beyond the requirements and why

1. **Modern ChatGPT-Inspired UI with Markdown & Code Blocks**: Full `react-markdown` + `remark-gfm` rendering (tables, lists, inline code, and styled fenced code blocks with horizontal scroll and copy-code buttons), copy-response buttons, floating scroll-to-bottom control, auto-resizing composer, reduced-motion / keyboard focus support, and error banners with one-click **Retry**.
2. **Collapsible Conversation Sidebar & Session Switching**: Desktop-collapsible / mobile-drawer sidebar listing recent sessions with active highlighting; clicking any prior session reloads its persisted history from SQLite via `GET /sessions/{session_id}/messages`.
3. **Dedicated Developer Inspector Drawer**: Optional right-side panel exposing selected `key_id`, `fallback_attempts`, cache status, latency, per-request tokens, and last backend error; `X-Simulate-Failure` controls appear only when `VITE_ENABLE_FAILURE_SIMULATION=true`.
4. **Windows PowerShell Lifecycle Scripts**: [scripts/start-local.ps1](scripts/start-local.ps1), [scripts/stop-local.ps1](scripts/stop-local.ps1), [scripts/verify-local.ps1](scripts/verify-local.ps1), [scripts/docker.ps1](scripts/docker.ps1), and [scripts/verify_live_provider.py](scripts/verify_live_provider.py) for repeatable local startup and real-provider verification.
5. **Startup Cache Handler Preload**: Preloads LiteLLM's lazy cache-hit modules during app initialization so the very first cache hit avoids cold-import latency overhead.
