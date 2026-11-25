# CI/CD & Branch Protection Guide

The GitHub Actions workflow in [.github/workflows/ci.yml](../.github/workflows/ci.yml) defines four independent jobs using only official `actions/*` actions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, `actions/upload-artifact@v4`):

1. **Backend (Python 3.12 + Pytest)** — installs `backend/requirements.txt`, runs `pytest -v --junitxml=test-results/pytest-report.xml` completely offline (no OpenRouter/API secrets), and uploads `backend-pytest-report`.
2. **Frontend (Node.js 22 + Vite Build)** — runs `npm ci`, `npm run build`, verifies all 9 mandatory `data-testid` attributes in `frontend/dist/assets/*.js`, and uploads `frontend-dist`.
3. **Backend Security Audit (pip-audit)** — runs `pip-audit -r requirements.txt` on `push`, `pull_request`, and every Monday at `06:00 UTC` (`schedule`), uploading `backend-pip-audit-report`.
4. **Frontend Security Audit (npm audit)** — runs `npm ci` and `npm audit --audit-level=high` on `push`, `pull_request`, and every Monday at `06:00 UTC` (`schedule`), uploading `frontend-npm-audit-report`.

---

## Configuring Required Status Checks on `main`

Once the repository is pushed to GitHub and the `CI` workflow has run at least once:

1. Open your GitHub repository → **Settings** → **Branches** (or **Rules** → **Rulesets**).
2. Click **Add branch protection rule** (or **New branch ruleset**) targeting branch pattern **`main`**.
3. Enable **Require a pull request before merging**.
4. Enable **Require status checks to pass before merging** (and optionally **Require branches to be up to date before merging**).
5. Search for and select these exact status check names:
   - `Backend (Python 3.12 + Pytest)`
   - `Frontend (Node.js 22 + Vite Build)`
   - `Backend Security Audit (pip-audit)`
   - `Frontend Security Audit (npm audit)`
   *(Optional: If you prefer advisory-only security checks, require only the first two build/test checks and monitor the audit jobs on PRs and weekly schedules.)*
6. Click **Create** / **Save changes**.
