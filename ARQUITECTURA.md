# Arquitectura — SERCOP Analytics

Contratación Pública Ecuador / SERCOP Analytics: API REST (FastAPI + SQLite) más una
UI de una sola página (Streamlit) para consultar y gestionar procesos de contratación
pública ecuatoriana, con herramientas para cargar datos desde el portal SERCOP
(protegido con CAPTCHA, por lo que la automatización no puede ser 100% headless).

## Vista general

```
┌─────────────────────┐        HTTP (X-API-Key)        ┌──────────────────────┐
│   app_ui.py          │ ───────────────────────────▶  │   src/main.py (API)   │
│   (Streamlit UI)      │ ◀───────────────────────────  │   FastAPI + SQLite    │
└─────────────────────┘                                 └──────────┬───────────┘
        │  usa                                                     │
        ▼                                                          ▼
┌─────────────────────┐                                 ┌──────────────────────┐
│  services/sercop.py   │                                 │  data/*.sqlite / .db  │
│  (único cliente HTTP  │                                 └──────────────────────┘
│   hacia la API)       │
└─────────────────────┘
        │  usa (solo explicar_desierta)
        ▼
┌─────────────────────┐        HTTP        ┌──────────────────────────────┐
│ services/            │ ─────────────────▶ │ RAG Contratación (Proyecto_02) │
│ criterio_juridico.py │                    │ proyecto externo, puerto 8001 │
└─────────────────────┘                    └──────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ scripts/  — batch jobs de un solo propósito, cada uno con su test       │
│ acceden a la base de datos DIRECTO vía src/database (no pasan por la API)│
│ salvo scripts/import_csv.py y los que llaman a services/*                │
└────────────────────────────────────────────────────────────────────────┘
```

## Componentes

### API — `src/`

- **`main.py`** — app FastAPI. Expone `/api/todos` (CRUD de contrataciones) y
  `/api/borradores` (CRUD de borradores/drafts). Monta además el router de
  `api_reportes.py`.
- **`api_reportes.py`** — router separado, `POST /api/generar-reporte` (genera
  reportes .docx a partir de una contratación).
- **`database.py`** — conexión y esquema SQLite (`DB_PATH`, funciones
  `get_all_contrataciones`, `update_contratacion`, etc.). Es el único módulo que
  habla SQL; todo lo demás pasa por sus funciones.
- **`models.py`** — esquemas Pydantic (request/response) para contrataciones y
  borradores. `explicacion_estado` tiene `max_length=2000`.
- **`auth.py`** — autenticación por API key (`X-API-Key`, `secrets.compare_digest`).
  Fail-closed: sin `API_KEY` configurada, todo endpoint protegido devuelve 401.

### UI — `app_ui.py`

Single-file Streamlit (~3.5k líneas). Todo el I/O contra el backend pasa por
`services/sercop.py` — la UI nunca llama a `requests` directamente. Incluye un
bloque de CSS neumorphist inyectado para el estilo visual.

### Capa de servicios — `services/`

- **`sercop.py`** — único cliente HTTP hacia la API FastAPI propia (`API_URL`,
  `API_KEY`). `obtener_contrataciones` cacheada con `@st.cache_data(ttl=600)`;
  las funciones CRUD de borradores son deliberadamente no-cacheadas.
- **`criterio_juridico.py`** — cliente HTTP hacia el RAG de Contratación Pública
  (`Proyecto_02`, proyecto externo en `tema_4/Proyecto_02`, puerto 8001 por
  defecto vía `RAG_CONTRATACION_URL`). `explicar_desierta()` nunca lanza
  excepción — devuelve `None` ante cualquier fallo, para que los scripts batch
  degraden proceso por proceso en vez de abortar.

### Scripts batch — `scripts/`

Un módulo por tarea, cada uno con su `tests/test_<nombre>.py`. Acceden a SQLite
directo vía `src.database` (no pasan por la API HTTP, no necesitan `API_KEY`),
salvo cuando dependen de un servicio externo (`services/*`).

| Script | Propósito |
|---|---|
| `scrape_portal.py` | Extracción de datos del portal SERCOP vía Playwright — ventana visible obligatoria (CAPTCHA manual). |
| `analizar_oficios_desierta.py` | 2ª pasada sobre procesos "Desierta": descarga el PDF del oficio SERCOP real citado en `motivo_estado_raw`, extrae texto (PyMuPDF) y pide al RAG una versión técnica adicional. Playwright, ventana visible por defecto. |
| `explicar_estado_desierta.py` | Genera la explicación en lenguaje llano de por qué un proceso quedó "Desierta", vía RAG (`services/criterio_juridico.py`), sin navegador. |
| `actualizar_motivos_desierta.py` | Actualiza/normaliza `motivo_estado_raw` para procesos "Desierta". |
| `actualizar_montos_adjudicados.py` | Actualiza montos adjudicados para procesos en estados adjudicables (incl. Recepción y mutuo acuerdo). |
| `especificaciones_tecnicas_generator.py` | Genera el documento .docx "Especificaciones Técnicas" (antes "Anexo 1"). |
| `importador_parametros.py` | Importador híbrido de "Parámetros técnicos": parser determinístico + respaldo vía API de Claude si no logra interpretar el archivo. |
| `importador_items.py` | Mismo patrón híbrido para la tabla "Ítems": detección de encabezado + fuzzy matching de columnas (`difflib`), catálogo CPC inyectado por `app_ui.py`. |
| `lectura_archivos_tabulares.py` | Lectura cruda de `.xlsx`/`.csv`/`.txt` con fallback de encoding, compartida por ambos importadores híbridos. |
| `report_generator.py` | Generación de reportes (usado por `api_reportes.py`). |
| `dashboard_analitico.py` | Lógica del dashboard analítico (pestaña "Dashboard Municipio de Guayaquil"). |
| `import_csv.py` | Carga masiva desde CSV. |
| `formato_ec.py` | Formato de números/moneda estilo Ecuador. |
| `tinymce_editor.py` | Integración del editor TinyMCE (usado junto a `assets/tinymce_editor/index.html`). |

### Datos y estáticos

- **`data/`** — `cpc_n9.csv` (catálogo CPC), `provincias_ecuador.geojson`
  (límites provinciales), además de las bases SQLite locales (ignoradas por git,
  entorno de producción local) y `oficios_txt/` (caché de texto de oficios
  extraído por `analizar_oficios_desierta.py`, ignorado por git).
- **`assets/`** — imágenes institucionales (escudo, header, footer) y el editor
  TinyMCE embebido.

### Configuración / infraestructura

- **`.streamlit/config.toml`** — configuración de tema/servidor de Streamlit.
- **`Dockerfile`**, **`.dockerignore`** — contenedorización.
- **`.github/workflows/main.yml`** — CI: `pytest` (bloqueante) + `ruff check .`
  (no bloqueante, `continue-on-error: true`).
- **`pyproject.toml`** — configuración de `ruff`.
- **`requirements.txt`** — dependencias (⚠ codificado en UTF-16).
- **`.claude/skills/run-app/`** — skill de Claude Code para levantar API + UI.

## Estructura de directorios

```
proyecto_1/
├── app_ui.py                          # UI Streamlit (single-file, ~3.5k líneas)
├── ARQUITECTURA.md
├── CLAUDE.md
├── README.md
├── Dockerfile
├── .dockerignore
├── pyproject.toml                     # config de ruff
├── requirements.txt                   # UTF-16 (!)
│
├── src/                                # API FastAPI
│   ├── main.py                         # app, endpoints /api/todos y /api/borradores
│   ├── api_reportes.py                 # router /api/generar-reporte
│   ├── database.py                     # conexión + esquema SQLite
│   ├── models.py                       # esquemas Pydantic
│   └── auth.py                         # autenticación por API key
│
├── services/                           # clientes HTTP hacia servicios externos/propios
│   ├── sercop.py                       # cliente hacia la API propia (src/main.py)
│   └── criterio_juridico.py            # cliente hacia el RAG (Proyecto_02, puerto 8001)
│
├── scripts/                            # jobs batch, uno por concern
│   ├── scrape_portal.py
│   ├── analizar_oficios_desierta.py
│   ├── explicar_estado_desierta.py
│   ├── actualizar_motivos_desierta.py
│   ├── actualizar_montos_adjudicados.py
│   ├── especificaciones_tecnicas_generator.py
│   ├── importador_parametros.py
│   ├── importador_items.py
│   ├── lectura_archivos_tabulares.py
│   ├── report_generator.py
│   ├── dashboard_analitico.py
│   ├── import_csv.py
│   ├── formato_ec.py
│   └── tinymce_editor.py
│
├── tests/                              # tests/test_<nombre>.py, uno por módulo de scripts/
│   ├── conftest.py                     # fixture `client` (TestClient + DB temporal)
│   └── test_*.py
│
├── data/
│   ├── cpc_n9.csv                      # catálogo CPC (estático, versionado)
│   ├── provincias_ecuador.geojson      # límites provinciales (estático, versionado)
│   ├── *.sqlite / *.db                 # bases locales (ignoradas por git)
│   └── oficios_txt/                    # caché de texto de oficios (ignorada por git)
│
├── assets/
│   ├── mimg_escudo.png
│   ├── mimg_header.jpg
│   ├── mimg_footer.jpg
│   └── tinymce_editor/index.html
│
├── .streamlit/
│   └── config.toml
│
├── .github/workflows/
│   └── main.yml                        # CI: pytest + ruff
│
└── .claude/skills/run-app/
    └── SKILL.md                        # cómo levantar API + UI en esta máquina
```

## Variables de entorno

| Variable | Usada por | Requerida | Notas |
|---|---|---|---|
| `API_KEY` | `src/auth.py`, `services/sercop.py` | Sí | En `.env`. Fail-closed: sin ella, todo endpoint protegido devuelve 401. |
| `API_URL` | `services/sercop.py` | No | Default `http://localhost:8000`. Solo env de proceso, no se lee de `.env`. |
| `ANTHROPIC_API_KEY` | `scripts/importador_parametros.py` | No | Solo fallback LLM cuando el parser determinístico no puede interpretar un archivo. |
| `RAG_CONTRATACION_URL` / `RAG_CONTRATACION_TIMEOUT_S` | `services/criterio_juridico.py` | No | Default `http://localhost:8001` / `60`. Necesarias para `explicar_estado_desierta.py` y `analizar_oficios_desierta.py`. |

## Notas de diseño

- **CAPTCHA-gated**: el portal SERCOP exige resolver un CAPTCHA humano en la
  búsqueda — por eso `scrape_portal.py` corre siempre con ventana visible
  (`headless=False`), nunca en background. La página de *detalle* de un proceso
  no pide CAPTCHA, lo que permite que `analizar_oficios_desierta.py` navegue
  esa parte del flujo, aunque por defecto también corre visible.
- **Scripts batch vs. API HTTP**: los scripts en `scripts/` acceden a SQLite
  directo vía `src.database`, no vía HTTP — evita depender de `API_KEY` y del
  servidor `uvicorn` estar corriendo para tareas batch/offline.
- **RAG externo desacoplado**: `criterio_juridico.py` nunca lanza excepción;
  si el RAG (`Proyecto_02`) no está disponible, los scripts que dependen de él
  simplemente marcan esos registros como pendientes y continúan con el resto.
