# Requirements Checklist

- [x] **P0**: FastAPI backend with `GET /health`, `POST /chat`, `GET /sessions/{session_id}/messages` (no extra endpoints; docs/openapi disabled)
- [x] **P0**: LiteLLM integration (`LLM_API_KEYS` -> `key_1`, `key_2`, ...), real `litellm.completion` invocation, automatic failover on 429/quota/5xx
- [x] **P0**: LiteLLM built-in response caching (`LIVE_INFERENCE` / `LLM_CACHE`, cross-session hits, `key_id=null` & `fallback_attempts=0`)
- [x] **P0**: `X-Simulate-Failure` header gated by `ENABLE_FAILURE_SIMULATION=true` (bypasses cache so simulations are never masked)
- [x] **P0**: Per-request `input_tokens`, `output_tokens` (with tokenizer fallback when omitted), monotonic `latency_ms`
- [x] **P1**: SQLite-only persistence (`DATABASE_URL`), auto-created schema, indexed `messages` table, failed requests not saved
- [x] **P1**: JSON-only error responses (`422`, `404`, `503`), restricted CORS, no secrets committed/logged
- [x] **P2**: React frontend with all mandatory `data-testid` attributes, new session per page load, error display, failover sim UI
- [x] **P3**: Multi-stage Dockerfiles, `docker-compose.yml` (`/data` volume), `Makefile` (`up`, `down`), `.env.example`, `.gitignore`
- [x] **P4**: Pytest suite covering all 20+ scenarios passing (`18 passed` in `tests/test_api.py`)
- [ ] **P5**: Live public deployment & live LLM key verification (deployment configs `render.yaml` & `frontend/vercel.json` ready; requires user API keys & hosting accounts)
- [x] **P6**: `README.md` (6 required headings), `DEMO_SCRIPT.md`, final quality audit
