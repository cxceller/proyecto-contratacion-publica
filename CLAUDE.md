# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Contratación Pública Ecuador / SERCOP Analytics: a FastAPI + SQLite REST API plus a single-file Streamlit UI to query and manage Ecuadorian public-procurement processes, with tools to load data from the SERCOP portal (CAPTCHA-gated, so no full automation is possible).

All identifiers, comments, and commit messages are in Spanish — keep new code consistent with that.

## Running

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn src.main:app --port 8000        # API
.venv/Scripts/python.exe -m streamlit run app_ui.py --server.port 8501   # UI (needs API running)
.venv/Scripts/python.exe -m pytest -q                                # tests
```

UI defaults to `API_URL=http://localhost:8000`; override via env var (not read from `.env`).

## Architecture

- `src/main.py` — FastAPI app, `/api/todos` + borradores (drafts) endpoints; also mounts the `src/api_reportes.py` router (not documented in README).
- `src/database.py` (schema/connection), `src/models.py` (Pydantic schemas), `src/auth.py` (API-key auth).
- `app_ui.py` — single-file Streamlit UI (~3.5k lines), talks to the API via `requests`. Has a custom neumorphist CSS block injected for styling — don't break it when touching layout/styles.
- `scripts/` — one module per concern, each paired with `tests/test_<nombre>.py`: `especificaciones_tecnicas_generator.py` (.docx generation), `report_generator.py`, `dashboard_analitico.py`, `formato_ec.py` (Ecuador number/currency formatting), `import_csv.py`, `scrape_portal.py` (Playwright, CAPTCHA-assisted).
- `data/cpc_n9.csv`, `data/provincias_ecuador.geojson` — static reference catalogs (CPC codes, province boundaries).

## Naming

"Especificaciones Técnicas" is the current name for what used to be called "Anexo 1" (renamed in commit `ef2a270`). Don't reintroduce "Anexo 1" / "anexo1_" naming in new code.

## Env vars

- `API_KEY` (in `.env`, repo root) — required for the API to accept requests. Auth is fail-closed: if unset, every protected endpoint returns 401 (see `src/auth.py`, uses `secrets.compare_digest`). Read by both `src/auth.py` and `app_ui.py`.
- `API_URL` — optional, process env only, defaults to `http://localhost:8000`.

## Testing

- `tests/conftest.py`'s `client` fixture builds a FastAPI `TestClient` against a temp SQLite DB per test (monkeypatches `database.DB_PATH`) plus a fixed test `API_KEY`; `src.main.app` is imported lazily inside the fixture so the monkeypatching takes effect first.
- `tests/test_auth.py` builds its own `TestClient` (no auto auth header) specifically to test missing/invalid-key scenarios.
- No pytest config file exists — no custom markers.

## Linting

`.venv/Scripts/python.exe -m ruff check .` (config in `pyproject.toml`). Not run in CI (none exists) — run it manually before committing. There were 18 pre-existing findings when ruff was set up; fixing them wasn't in scope, so don't assume a clean baseline.

## Gotchas

- `requirements.txt` is UTF-16 encoded — reading/editing with plain UTF-8 tools shows garbled text; preserve the encoding when adding a dependency (`open(..., encoding="utf-16")`).
- `scripts/scrape_portal.py` opens a visible Chromium window and needs a real desktop session (the user solves a CAPTCHA manually) — never run it headless/backgrounded.
- No formatter or CI is configured.
