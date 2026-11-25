# Implementation Plan

1. **Backend Core & Dependencies (`backend/`)**
   - Create virtual environment, verify `fastapi`, `uvicorn`, `litellm`, `pytest`, `httpx` install cleanly on Python 3.14.6.
   - Implement `config.py`, `database.py`, `models.py`, `schemas.py`, `services/litellm_service.py`, `routers/health.py`, `routers/chat.py`, `routers/sessions.py`, and `main.py`.
2. **Backend Automated Tests (`backend/tests/`)**
   - Write and run pytest covering all 20 required scenarios (health, validation, multi-turn, session isolation, history 404, cross-session caching, failover, 503 non-persistence, per-request tokens, SQLite persistence, CORS, simulation toggle).
3. **Frontend (`frontend/`)**
   - Scaffold React + Vite app with all mandatory `data-testid` attributes, metadata badges, system prompt input, error alerts, theme toggle, and failover simulation drawer.
   - Run production build (`npm run build`) and verify zero errors.
4. **Docker, Tooling & Docs**
   - Write multi-stage `backend/Dockerfile`, multi-stage `frontend/Dockerfile`, `docker-compose.yml`, `Makefile`, `.env.example`, `.gitignore`, `README.md`, `DEMO_SCRIPT.md`, and final audit table.
5. **End-to-End Local Verification**
   - Run backend + frontend locally and verify API contract and UI elements.
