---
name: run-app
description: Launch the API (FastAPI/uvicorn) and Streamlit UI for this project to manually verify a change. Use whenever asked to run, start, or test the app end-to-end (not just run pytest).
---

Both processes must run together: the Streamlit UI calls the API over HTTP.

## Start

```bash
# From the repo root.
.venv/Scripts/python.exe -m uvicorn src.main:app --port 8000 > /tmp/uvicorn.log 2>&1 &
disown
timeout 30 bash -c 'until curl -sf http://localhost:8000/docs >/dev/null; do sleep 1; done' && echo "API UP"

.venv/Scripts/python.exe -m streamlit run app_ui.py --server.port 8501 --server.headless true > /tmp/streamlit.log 2>&1 &
disown
timeout 40 bash -c 'until curl -sf http://localhost:8501 >/dev/null; do sleep 1; done' && echo "STREAMLIT UP"
```

Run both `timeout ... curl` waits via the Bash tool's `run_in_background: true` — don't block on them.

## Stop / restart (Windows gotcha)

On this machine, `lsof -ti:PORT -sTCP:LISTEN | xargs -r kill` frequently reports success but does **not** actually free the port (Git Bash PID often doesn't match the real Windows process). Before relaunching, always confirm and kill via `netstat`/`taskkill` instead:

```bash
netstat -ano | grep ':8501' | grep LISTENING   # get the real PID
taskkill //F //PID <pid>
```

Verify the port is actually free (only `TIME_WAIT` lines, no `LISTENING`) before starting a new process on it — a stale leftover process will keep serving old code and cause confusing "nothing changed" results.

## Requirements

- `API_KEY` must be set (it's in `.env` at repo root, loaded via `python-dotenv`). Auth is fail-closed — without it every `/api/*` call returns 401.
- If you need to hit the API directly (not through the UI), send `X-API-Key: <value from .env>`.

## Driving the UI

Playwright (already installed, Chromium browser already downloaded — used by `scripts/scrape_portal.py`) works headlessly against `http://localhost:8501` for screenshots/interaction checks. `chromium-cli` is not installed on this machine.

Streamlit-specific waits:
- A page transition triggered by `st.rerun()` (e.g. clicking a sidebar nav button) shows "RUNNING..." top-right while in flight. `st.tabs()` switches do NOT trigger a rerun (client-side only) — don't wait for a rerun signal after those.
- Selecting an item that loads saved state (e.g. "Cargar contratación guardada") can take **two** chained reruns (fetch → `st.rerun()` → apply state). Wait for the actual resulting text/caption to appear, not just for "RUNNING" to disappear once — the gap between the two reruns is easy to mistake for "done".
- The `st.data_editor` grid is a canvas-based component (glide-data-grid); clicking/editing individual cells via Playwright is unreliable. Prefer seeding data through the API (`POST /api/borradores`) and loading it via the UI's selector when a test needs realistic table data.
