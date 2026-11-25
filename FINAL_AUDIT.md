# Final Evaluation Audit — Lyftr AI Full-Stack Assignment

**Audit Date:** 2026-11-25  
**Repository:** `C:\Users\user\Lyftr`  
**Environment:** Windows 11, Python 3.14.6, Node.js 24.18.0, npm 11.17.0, Git 2.54.0 (Docker, `make`, hosting CLIs, and LLM API keys unavailable in this environment)

---

## 1. Bugs Found & Fixed During Phase 1–2 Audit

1. **Empty/Malformed Provider Reply Poisoning LiteLLM Cache (`backend/app/services/cache_service.py`, `backend/app/services/litellm_service.py`)**:
   - **Bug**: `litellm.completion(..., caching=True)` cached an empty/whitespace response from `key_1` before our application validated `reply_text`, causing `key_2` to receive a poisoned cache hit instead of failing over. Additionally, non-string `content` (e.g., list blocks or malformed ints) could raise `AttributeError` and misclassify as `400`.
   - **Fix**: Hardened `_extract_reply_text()` for `None`, list content blocks, and non-string payloads, and added `CacheService.evict()` to synchronously delete empty-reply entries before failing over to `key_2`.
2. **Unsupported `CACHE_TYPE=disk` Crash in LiteLLM 1.111.0 (`backend/app/services/cache_service.py`)**:
   - **Bug**: LiteLLM 1.111.0 removed the `disk` cache backend (`ValueError: Unsupported cache type 'disk'`).
   - **Fix**: Safely log a warning and fall back to `Cache(type="local")` if a non-`local` `CACHE_TYPE` is supplied.
3. **Concurrent Same-Session History Race (`backend/app/routers/chat.py`)**:
   - **Bug**: Two simultaneous `POST /chat` requests for the same `session_id` could read identical pre-turn history in parallel threads, losing turn ordering in LLM context.
   - **Fix**: Added a reference-counted `_SessionLockManager` to serialize concurrent requests sharing the same `session_id` while keeping different sessions parallel.
4. **Same-Tick Duplicate Submit Guard (`frontend/src/App.jsx`)**:
   - **Fix**: Added a synchronous `inFlightRef` guard alongside `isLoading` so rapid double-clicks/Enters cannot fire duplicate requests before React re-renders.
5. **CORS Trailing Slash Normalization & Docker Build Context Hygiene (`backend/app/config.py`, `backend/.dockerignore`, `frontend/.dockerignore`)**:
   - **Fix**: Normalized `ALLOWED_ORIGINS` with `.rstrip("/")` and added `.dockerignore` files excluding `.venv`, `node_modules`, `dist`, and local SQLite files.

---

## 2. Independent Audit Matrix

| Requirement | Status | Test Command | Actual Result | Evidence | Remaining Blocker |
|---|---|---|---|---|---|
| Backend Automated Suite (29 tests) | **PASS** | `cd backend && .venv\Scripts\pytest.exe -v` | `29 passed, 13 warnings in 13.45s` | `test_api.py` (18 tests) + `test_qa_audit.py` (11 tests): validation, multi-turn, concurrency, rollback, CORS, simulation, caching | None for offline/adapter suite |
| API Contract (3 endpoints, exact schema, JSON errors) | **PASS** | `pytest -v` + `smoke_verify.py` + `TestClient` route check | `HEALTH: 200`, `HTTP_404: 404`, `HTTP_422: 422`, `HTTP_503: 503`; `/docs`, `/redoc`, `/openapi.json` return `404` | `test_01`–`test_09`, `test_21`, `test_qa_cors_preflight_trailing_slash_and_malformed_json`, live `uvicorn` `:8011` | None |
| SQLite Persistence, Rollback & Concurrency | **PASS** | `pytest -v` (`test_06`–`08`, `test_16`, `test_18`, `test_qa_*`) | Restart persistence, atomic rollback, parallel & same-session serialization passed | `test_18_sqlite_persistence_across_app_restart`, `test_qa_sqlite_transaction_rollback_on_write_failure`, `test_qa_same_session_concurrent_messages_serialize_cleanly` | Container volume restart requires Docker |
| Failure Simulation (`X-Simulate-Failure`) | **PASS** | `pytest -v` (`test_13`–`16`, `test_20`, `test_qa_invalid_*`) + live `uvicorn` | `key_1=429`/`500` → `key_2`; `*=429` → `503`; disabled mode ignores header; invalid headers safe | Verified on `TestClient` & live `uvicorn` (`HTTP_503: 503 {"detail":"all providers unavailable"}`) | None |
| Token Tracking & Latency | **PASS** | `pytest -v` (`test_02`, `test_10_11_12`, `test_17`) | Per-request `input_tokens`, `output_tokens`, `litellm.token_counter` fallback, monotonic `latency_ms` passed | `test_17_per_request_tokens_and_tokenizer_fallback` | Live provider token comparison needs real API keys |
| LiteLLM Integration & Key Failover | **PARTIAL** | `pytest -v` (`test_13`, `test_qa_timeout_quota_and_three_key_failover`, `test_qa_empty_and_malformed_*`) | Real `litellm.completion` + real `RateLimitError`/`Timeout`/quota/`5xx`/empty failover verified with patched `vertex_chat_completion` adapter | `test_13`, `test_qa_timeout_quota_and_three_key_failover`, `test_qa_authentication_failure_stops_without_retrying_all_keys` | **Real LLM API keys** (`LLM_API_KEYS`) unavailable in environment |
| Response Caching (`LLM_CACHE` / `LIVE_INFERENCE`) | **PARTIAL** | `pytest -v` (`test_10_11_12`, `test_qa_cache_isolation_*`, `test_qa_simulation_disabled_*`) | Real `litellm.Cache(type="local")` cross-session hit, system-prompt/history isolation, and preserved tokens verified with patched adapter | `test_10_11_12` (`call_count == 3` for 4 requests, `key_id=None`, `latency_ms` lower than `0.25s` live call) | **Real LLM API keys** needed to measure live network cache speedup |
| React Frontend Build & Mandatory `data-testid`s | **PASS** | `cd frontend && npm run build` + `smoke_verify.py` + `VITE_API_BASE_URL` check | Built in `1.34s` / `1.19s`; `FRONTEND: 200 has_root= True`; `MISSING_TESTIDS: []`; `PROD_URL_BAKED=True LOCALHOST_PRESENT=False` | All 9 `data-testid` attributes present in `frontend/dist/assets/*.js`; no hardcoded localhost when `VITE_API_BASE_URL` set | None |
| Security Audit (Secrets, `.gitignore`, CORS, Errors) | **PASS** | PowerShell `Select-String` secret scan + `git status` + `TestClient` CORS/error tests | `SECRET_MATCHES: 0`; `.env` absent and ignored; no stack traces or keys in responses | `test_02`, `test_19`, `test_21`, `test_qa_authentication_failure_*`, `test_qa_cors_preflight_*` | None |
| Real Provider Verification (Phase 3 items 1–8) | **NOT TESTED** | Checked `Get-ChildItem Env:` and `.env` presence; prepared `scripts/verify_live_provider.py` | No API keys configured (`Test-Path .env` = `False`) | Environment check output; 9-step acceptance runner syntax verified (`--help`) | Provide ≥2 real keys in `.env` (`LLM_API_KEYS`) and run `python scripts/verify_live_provider.py` |
| Docker, Compose & Makefile (`make up` / `make down`) | **NOT TESTED** | `Get-Command docker`, `Get-Command make`; prepared `scripts/docker.ps1` | Neither `docker` nor `make` installed on host | Static configs verified: `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `.dockerignore`, `Makefile`, `scripts/docker.ps1`, `test_qa_database_url_docker_posix_parsing` | Run `make up && make down && make up` (or `.\scripts\docker.ps1 verify`) on a machine with Docker |
| Public Deployment (GitHub, Render, Vercel) | **NOT TESTED** | Checked `gh`, `vercel`, `render`, `railway` CLIs | None installed or authenticated locally | `render.yaml` (with 1 GB `/data` disk) & `frontend/vercel.json` prepared | Push to GitHub and deploy to Render + Vercel with user credentials |
