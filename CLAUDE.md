# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Contratación Pública Ecuador / SERCOP Analytics: a FastAPI + SQLite REST API plus a Streamlit UI (`app_ui.py` + `ui/`) to query and manage Ecuadorian public-procurement processes, with tools to load data from the SERCOP portal (CAPTCHA-gated, so no full automation is possible).

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
- `services/sercop.py` — the only place that calls the FastAPI backend (via `requests`) or knows its URLs/endpoints; `app_ui.py` imports and calls these functions instead of talking to the API directly. `obtener_contrataciones` is `@st.cache_data(ttl=600)` (survives navigating between views); the borrador (draft) CRUD functions are deliberately uncached so a save/delete is reflected immediately on the next rerun.
- `services/criterio_juridico.py` — HTTP client to an external RAG service ("Proyecto_02", a separate legal RAG for Ecuadorian public-procurement law, not part of this repo — see Gotchas) that generates the "Explicación (Desierta)" text (`scripts/explicar_estado_desierta.py`, `explicacion_estado` column) grounded in the actual indexed LOSNCP/Reglamento instead of an ungrounded direct LLM call. `explicar_desierta()` never raises — returns `None` on any failure so a batch run degrades one process at a time instead of aborting.
- `app_ui.py` — Streamlit UI (~3k lines), consumes `services/sercop.py` for all backend I/O. Has a custom neumorphist CSS block injected for styling — don't break it when touching layout/styles.
- `ui/` — split out of `app_ui.py` in P0-1 of the UI/UX improvement plan: `tema.py` (shared `COLOR_*`/`PALETA_DATOS` constants, imported by both `app_ui.py` and the module below), `especificaciones_tecnicas.py` (~2.1k lines — the entire "Especificaciones Técnicas" domain: borrador CRUD, the shadow-dict widget-state pattern, CPC autocomplete, HTML preview builder, `.docx` generation trigger). `app_ui.py` re-imports `render_formularios_y_registro`, `render_treemap_items_especificaciones_tecnicas`, `_dataframe_items_especificaciones_tecnicas_vacio` from it (the Dashboard's "Presupuesto por Ítem" tab needs the latter two). `_cargar_catalogo_cpc()` (CPC catalog loader) now lives here too, not in `app_ui.py`.
- `scripts/` — one module per concern, each paired with `tests/test_<nombre>.py`: `especificaciones_tecnicas_generator.py` (.docx generation), `report_generator.py`, `dashboard_analitico.py`, `formato_ec.py` (Ecuador number/currency formatting), `import_csv.py`, `scrape_portal.py` (Playwright, CAPTCHA-assisted), `importador_parametros.py` (importador híbrido de "Parámetros técnicos" en Especificaciones Técnicas: parser determinístico + respaldo vía API de Claude — ver Env vars), `importador_items.py` (mismo patrón híbrido para la tabla "Ítems": detección de encabezado + fuzzy matching de columnas vía `difflib`, con el catálogo CPC inyectado por `ui/especificaciones_tecnicas.py`, no cargado por el propio módulo), `lectura_archivos_tabulares.py` (lectura cruda de .xlsx/.csv/.txt con fallback de encoding, compartida por ambos importadores híbridos).
- `data/cpc_n9.csv`, `data/provincias_ecuador.geojson` — static reference catalogs (CPC codes, province boundaries).
- `scripts/completar_montos_resolucion_pdf.py` — parses the PDF de Resolución de Adjudicación to fill in Monto Adjudicado; writes `montos_extraidos.csv`/`montos_fallidos.csv` to the repo root (gitignored).
- `scripts/descargar_snapshot_db.py` — Cloud Run only (invoked by `start.sh`): downloads the SQLite snapshot from Cloud Storage to `/tmp/sercop.db` using the attached service account's metadata-server token (no `google-cloud-storage` dependency — see Deployment). No-ops if `/tmp/sercop.db` already exists; exits non-zero (aborting the container) if `SERCOP_DB_BUCKET` is unset or the download fails.

## Naming

"Especificaciones Técnicas" is the current name for what used to be called "Anexo 1" (renamed in commit `ef2a270`). Don't reintroduce "Anexo 1" / "anexo1_" naming in new code.

## Env vars

- `API_KEY` (in `.env`, repo root) — required for the API to accept requests. Auth is fail-closed: if unset, every protected endpoint returns 401 (see `src/auth.py`, uses `secrets.compare_digest`). Read by both `src/auth.py` and `services/sercop.py`.
- `API_URL` — optional, process env only, defaults to `http://localhost:8000`. Read by `services/sercop.py`.
- `ANTHROPIC_API_KEY` (in `.env`, repo root) — only used by `scripts/importador_parametros.py` as the LLM fallback when the deterministic "Parámetros técnicos" file parser can't confidently interpret a file's structure. Not required for the app to run: the fast path never calls the API, and if the LLM path is needed but the key is missing/invalid, the uploader shows a retryable error instead of crashing.
- `RAG_CONTRATACION_URL` / `RAG_CONTRATACION_TIMEOUT_S` (in `.env`, repo root) — read by `services/criterio_juridico.py`. Default `http://localhost:8001` / `60`. Only needed to run `scripts/explicar_estado_desierta.py`; the rest of the app doesn't touch this.
- `DB_PATH` — optional, process env only. Read by `src/database.py`; defaults to `data/contrataciones.db` locally, or `/tmp/sercop.db` when `K_SERVICE` is set (Cloud Run — `/app` is root-owned, `appuser` can't write there). See Deployment.
- `SERCOP_DB_BUCKET` / `SERCOP_DB_OBJECT` — Cloud Run only, read by `scripts/descargar_snapshot_db.py`. `SERCOP_DB_OBJECT` defaults to `contrataciones.db`. Set on the Cloud Run service (`gcloud run services update ... --set-env-vars`), not in `.env`. See Deployment.

## Testing

- `tests/conftest.py`'s `client` fixture builds a FastAPI `TestClient` against a temp SQLite DB per test (monkeypatches `database.DB_PATH`) plus a fixed test `API_KEY`; `src.main.app` is imported lazily inside the fixture so the monkeypatching takes effect first.
- `tests/test_auth.py` builds its own `TestClient` (no auto auth header) specifically to test missing/invalid-key scenarios.
- No pytest config file exists — no custom markers.

## Linting

`.venv/Scripts/python.exe -m ruff check .` (config in `pyproject.toml`). Also run in CI (`.github/workflows/main.yml`, `ruff check .` step) with `continue-on-error: true`, so lint findings are visible in the run but don't fail it. There were 18 pre-existing findings when ruff was set up; fixing them wasn't in scope, so don't assume a clean baseline.

## Deployment

- Single-container Cloud Run deploy: `Dockerfile` (python:3.11-slim) + `start.sh` run both FastAPI and Streamlit in the same container. `start.sh` starts `uvicorn` on fixed internal port 8000, waits for it via `/dev/tcp/localhost/8000` (bash builtin — `netcat` isn't installed in `python:3.11-slim`), then starts `streamlit` on `${PORT:-8080}` bound to `0.0.0.0` (`PORT` is injected by Cloud Run, not read from `.env`). If `uvicorn` dies before it starts accepting connections, `start.sh` aborts the container (propagating uvicorn's exit code) instead of starting Streamlit against a dead API.
- `pip install -r requirements.txt` runs as root before `USER appuser` is set — only the runtime process is unprivileged, not the install step.
- No `cloudbuild.yaml` or deploy workflow in `.github/workflows/` — the Cloud Build trigger is configured directly in Google Cloud Console, not tracked in this repo.
- **Database persistence**: `data/*.db` is gitignored (see `CLAUDE.local.md`, which forbids committing it) and Cloud Build only sees what's pushed to git, so the SQLite file can't be baked into the image via `COPY`. Instead, on Cloud Run (`K_SERVICE` set) `start.sh` runs `scripts/descargar_snapshot_db.py` before `uvicorn`, which downloads a snapshot from a private Cloud Storage bucket to `/tmp/sercop.db` (the `DB_PATH` default there) using the service account's metadata-server token — no `google-cloud-storage` dependency (adding it would pull in ~14 packages and force a `protobuf` 5→7 / `requests` bump), just `requests` calling the GCS JSON API directly. It only downloads if `/tmp/sercop.db` doesn't already exist, and aborts the container if `SERCOP_DB_BUCKET` is unset or the download fails (never falls back to a silent empty DB).
  - **Refreshing data**: re-upload the `.db` to the bucket (`gsutil cp`) — no rebuild/redeploy needed. A cold-started instance downloads the new snapshot; instances already running keep whatever copy they downloaded until they're recycled.
  - **Caveat**: `/tmp` is per-instance and wiped on every restart/redeploy/cold start. Any writes made live through the deployed UI (e.g. borradores de Especificaciones Técnicas) are lost when the instance recycles, and with autoscaling >1 instance, each instance's `/tmp/sercop.db` can diverge from the others (no shared state). Fine for a read-mostly/reporting deployment; if live multi-instance writes need to persist and stay consistent, migrate to Cloud SQL instead (real migration, not a config change — see the `PRAGMA`/`create_function`/WAL usage in `src/database.py`).

## Gotchas

- `requirements.txt` is UTF-16 encoded — reading/editing with plain UTF-8 tools shows garbled text; preserve the encoding when adding a dependency (`open(..., encoding="utf-16")`).
- `requirements.txt`: `pywin32` is commented out — it's Windows-only and breaks `pip install` inside the Linux-based Cloud Run container; `numpy` is pinned as a relaxed `>=2.0.0` range for the same Linux-compatibility reason.
- `scripts/scrape_portal.py` opens a visible Chromium window and needs a real desktop session (the user solves a CAPTCHA manually) — never run it headless/backgrounded.
- No formatter is configured. CI exists (`.github/workflows/main.yml`, GitHub Actions) and runs `pytest` (blocking) plus `ruff check .` (non-blocking, `continue-on-error: true`) on push to `main`.
- On this machine's network, calls to `api.anthropic.com` fail TLS validation (`CERTIFICATE_VERIFY_FAILED` / surfaces as `anthropic.APIConnectionError("Connection error.")`) because `httpx` validates against `certifi`'s public CA bundle, which doesn't include this network's TLS-inspecting proxy CA — even though Windows itself trusts it. `scripts/importador_parametros.py` calls `truststore.inject_into_ssl()` at import time to make Python validate against the OS certificate store instead; don't remove it without confirming outbound HTTPS to `api.anthropic.com` still works.
- `scripts/explicar_estado_desierta.py` needs the RAG service ("Proyecto_02", at `tema_4/Proyecto_02` on this machine, a separate repo/venv — not part of this project) running on `RAG_CONTRATACION_URL` (default port 8001) — `uvicorn src.api.main:app --port 8001` from that project's own venv. Without it, `services/criterio_juridico.py` just returns `None` per process (no crash), so the script silently produces 0 explicaciones instead of failing loudly — check the RAG is actually up if a batch run reports everything as "con_error".
