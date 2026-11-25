# Localhost Repair & Acceptance Report

**Date:** 2026-11-25  
**Workspace:** `C:\Users\user\Lyftr`

---

## 1. Actual Localhost Failure Root Causes

Diagnostics (`Get-NetTCPConnection`, `Test-NetConnection`, `Resolve-DnsName localhost`, and live process probes) identified four concrete causes for localhost failing in the browser:

1. **No Local Server Runner / Stopped Processes**: Ports `3000`, `5173`, and `8000` had zero listening sockets (`TcpTestSucceeded : False`), and there was no dedicated local start/stop script (`scripts/start-local.ps1`).
2. **Backend Dependency Scope + Cold LiteLLM Startup**: Global Python (`C:\Python314\python.exe`) lacks `fastapi`, `litellm`, and `orjson` (`No module named 'fastapi'`), so running `python -m uvicorn` outside `backend\.venv` fails immediately. Even inside `.venv`, cold `litellm` import takes >5 seconds on Windows (connection refused at `t=5s` before Uvicorn finishes binding at `t≈6–10s`).
3. **Root `.env` Not Loaded by Backend + Missing API Keys**: `backend/app/config.py` previously set `env_file=".env"`, which only checked `backend/.env` when launched from `backend/` and ignored repository-root `.env`. Without `LLM_API_KEYS`, `/health` returns HTTP `503 {"detail":"no LLM keys configured"}`, which the frontend previously displayed generically as `"Gateway offline"`.
4. **Windows IPv6 `localhost` (`::1`) vs IPv4 (`127.0.0.1`) Mismatch**: `Resolve-DnsName localhost` resolves `::1` before `127.0.0.1`, while `frontend/src/api/chatApi.js` defaulted to `http://localhost:8000` and `vite`/`uvicorn` bound `127.0.0.1` (IPv4). Added `frontend/.env.development` with `VITE_API_BASE_URL=http://127.0.0.1:8000` while keeping production builds free of hardcoded localhost URLs.

---

## 2. Evidence from Commands & Logs

- **Initial port/DNS probe**:
  - `Get-NetTCPConnection -State Listen` on `3000,5173,8000`: empty (no listening servers).
  - `Resolve-DnsName localhost`: `::1` (AAAA) followed by `127.0.0.1` (A); `ProxyEnable : 0`.
- **Global vs `.venv` Python check**:
  - `C:\Python314\python.exe`: `global fastapi FAIL: No module named 'fastapi'`, `global litellm FAIL`, `global orjson FAIL`.
  - `C:\Users\user\Lyftr\backend\.venv\Scripts\python.exe`: `venv imports ok`.
- **Startup & verification**:
  - `.\scripts\start-local.ps1` started FastAPI (`http://127.0.0.1:8000`) and Vite (`http://127.0.0.1:3000`), writing logs to `logs/backend.log` and `logs/frontend.log`.
  - `.\scripts\verify-local.ps1` passed all 8 local checks (`HTTP 503 {"detail":"no LLM keys configured"}` on `/health`, `200` on `/`, `VITE_API_BASE_URL=http://127.0.0.1:8000`, SQLite tables `['messages', 'sessions', 'sqlite_sequence']`, `404`, `422`, `503` for `*=429`, and all 9 `data-testid`s).

---

## 3. Files Changed

- [backend/app/config.py](backend/app/config.py): Load both root `.env` (`_ROOT_ENV`) and `backend/.env` (`_BACKEND_ENV`).
- [frontend/.env.development](frontend/.env.development): Set `VITE_API_BASE_URL=http://127.0.0.1:8000` for Vite dev mode.
- [frontend/src/api/chatApi.js](frontend/src/api/chatApi.js): Default to `http://127.0.0.1:8000` only in `DEV` mode; distinguish `503` degraded health (`no LLM keys configured`) from unreachable backend.
- [frontend/src/components/Sidebar.jsx](frontend/src/components/Sidebar.jsx): Show `"Backend up • no LLM keys configured"` when `/health` returns `503` vs `"Gateway offline (cannot reach backend)"` when unreachable.
- [frontend/src/components/MessageItem.jsx](frontend/src/components/MessageItem.jsx): Display `null` (not `cache`) when `key_id` is `null`.
- [scripts/start-local.ps1](scripts/start-local.ps1), [scripts/stop-local.ps1](scripts/stop-local.ps1), [scripts/verify-local.ps1](scripts/verify-local.ps1): Created reliable Windows startup, PID-scoped shutdown, and local verification scripts.
- [scripts/verify_live_provider.py](scripts/verify_live_provider.py): Skip gracefully as `NOT TESTED` when real keys are absent; avoid flaky strict latency inequality on fast networks.
- [.env.example](.env.example), [.gitignore](.gitignore), [README.md](README.md), [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md), [FINAL_AUDIT.md](FINAL_AUDIT.md): Fixed `CACHE_TYPE=local` documentation, `key_id=null` wording, PowerShell script docs, and `logs/` ignore rule.

---

## 4. Verification Summary

| Check | Status | Evidence |
|---|---|---|
| Backend startup (`127.0.0.1:8000`) | **PASS** | `start-local.ps1` bound `127.0.0.1:8000`; `logs/backend.log` shows `Uvicorn running on http://127.0.0.1:8000` |
| Frontend startup (`127.0.0.1:3000`) | **PASS** | `start-local.ps1` bound `127.0.0.1:3000`; `logs/frontend.log` shows `VITE v6.4.6 ready`; both `http://127.0.0.1:3000/` and `http://localhost:3000/` returned `200` |
| Frontend/backend connectivity | **PASS** | Headless Edge (`msedge.exe --headless --dump-dom http://127.0.0.1:3000/`) executed React and fetched `http://127.0.0.1:8000/health`, rendering `Backend up • no LLM keys configured` |
| Automated tests (`pytest -v`, `npm run build`) | **PASS** | `29 passed, 13 warnings in 16.70s`; `vite build` succeeded in `1.24s` (`dist/assets/index-B8NkjXvM.js` `235.65 kB`) |
| Local acceptance (`verify-local.ps1`) | **PASS** | `LOCAL VERIFICATION PASSED` across all 8 checks (`/health`, `/`, dev URL, SQLite tables, 404, 422, 503 `*=429`, 9 `data-testid`s) |
| Interactive Chrome DevTools browser clicks | **NOT TESTED** | `chrome_devtools` MCP could not attach (`DevToolsActivePort` missing in `AppData\Local\Google\Chrome\User Data`); initial React + live `/health` fetch verified via headless Edge |
| Real external LLM provider (`verify_live_provider.py`) | **NOT TESTED** | Returned `SKIPPED (NOT TESTED): No real LLM_API_KEYS configured on backend.` |
| Docker (`make up` / `make down`) & public deploy | **NOT TESTED** | `docker`, `make`, and hosting CLIs (`gh`, `vercel`, `render`) unavailable on host |

---

## 5. Remaining Blockers

1. **Real LLM API Keys**: No `.env` with `LLM_API_KEYS` exists yet, so `/health` accurately reports `503 {"detail":"no LLM keys configured"}` and live inference/failover cannot execute externally.
2. **Interactive Browser Tooling**: Chrome remote debugging (`chrome://inspect/#remote-debugging`) is not enabled on this machine for `chrome_devtools` MCP interactive clicking.
3. **Docker & Hosting Credentials**: Docker Desktop, GNU Make, and Render/Vercel/GitHub credentials are not present on this host.

---

## 6. Exact Command to Start the Project in the Future

```powershell
cd C:\Users\user\Lyftr
.\scripts\start-local.ps1
```

Then open **`http://127.0.0.1:3000`** in your browser. To verify locally or stop the servers:

```powershell
.\scripts\verify-local.ps1
.\scripts\stop-local.ps1
```
