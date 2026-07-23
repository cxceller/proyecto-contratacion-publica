# Contratación Pública Ecuador

API REST (FastAPI + SQLite) e interfaz web (Streamlit) para consultar y
gestionar procesos de contratación pública del Ecuador, con herramientas
para cargar datos desde el portal de [SERCOP](https://www.compraspublicas.gob.ec/).

## Estructura del proyecto

```
src/                  API (FastAPI), modelos (Pydantic) y acceso a datos (SQLite)
  main.py             Endpoints REST
  models.py           Esquemas de entrada/salida
  database.py         Conexion y esquema SQLite
app_ui.py             Interfaz Streamlit (consume la API via requests)
scripts/
  import_csv.py       Importa un CSV/Excel exportado manualmente del portal
  scrape_portal.py    Abre Chromium para que resuelvas el CAPTCHA y extrae los resultados
tests/
  test_todos.py       Tests de la API (pytest + TestClient)
data/
  contrataciones.db   Base de datos SQLite (se crea automaticamente)
```

## Requisitos

- Python 3.12
- Un entorno virtual en `.venv` (ya incluido en este proyecto)

Instalar dependencias:

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Si vas a usar el scraper (`scripts/scrape_portal.py`), instala tambien el
navegador de Playwright (una sola vez):

```bash
.venv/Scripts/python.exe -m playwright install chromium
```

## Levantar la API

```bash
.venv/Scripts/python.exe -m uvicorn src.main:app --port 8000
```

La base de datos SQLite (`data/contrataciones.db`) se crea automaticamente
al arrancar si no existe.

### Endpoints

| Metodo | Ruta                         | Descripcion                                   |
|--------|------------------------------|------------------------------------------------|
| GET    | `/api/todos`                 | Lista procesos (filtros: `status`, `fecha_inicio`, `fecha_fin`, `palabra_clave`) |
| GET    | `/api/todos/{id}`             | Obtiene un proceso por id                      |
| POST   | `/api/todos`                  | Crea un proceso                                |
| PATCH  | `/api/todos/{id}`             | Actualiza campos de un proceso                 |
| DELETE | `/api/todos/{id}`             | Elimina un proceso                             |
| DELETE | `/api/todos`                  | Elimina **todos** los procesos (vaciar la base de datos) |

El filtro `status` compara por prefijo (no igualdad exacta), porque el
portal de SERCOP a veces trunca el estado (ej. `"Adjudicado -"`, `"Terminado U"`).

## Levantar la interfaz Streamlit

Con la API ya corriendo en otra terminal:

```bash
.venv/Scripts/python.exe -m streamlit run app_ui.py --server.port 8501
```

Por defecto apunta a `http://localhost:8000`; si la API corre en otro host/puerto,
usa la variable de entorno `API_URL`:

```bash
API_URL=http://localhost:8010 .venv/Scripts/python.exe -m streamlit run app_ui.py --server.port 8501
```

La interfaz permite buscar/filtrar por estado, rango de fechas y palabra clave,
ver contadores por estado, crear un proceso nuevo, eliminar por id, descargar
la tabla como CSV y vaciar la base de datos por completo (en la barra lateral,
con doble confirmacion para evitar borrados accidentales). En la tabla de
resultados, el "Código" de cada proceso es un enlace clicable que abre en una
pestaña nueva el detalle del proceso en el portal de SERCOP (si se conoce su
URL, ej. procesos traidos por `scrape_portal.py`).

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

Los tests usan una base de datos SQLite temporal (aislada por test), no tocan
`data/contrataciones.db`.

## Cargar datos

El portal de SERCOP exige resolver un CAPTCHA para buscar procesos, asi que
no hay forma de automatizar la carga de datos reales de punta a punta. Hay
dos formas de traer datos a la base local:

### 1. Importar un CSV/Excel exportado manualmente

Si ya hiciste la busqueda en el portal y exportaste el resultado:

```bash
.venv/Scripts/python.exe scripts/import_csv.py ruta/al/archivo.csv
.venv/Scripts/python.exe scripts/import_csv.py ruta/al/archivo.xlsx [--palabra-clave TEXTO]
```

### 2. Scraping asistido (`scrape_portal.py`)

Abre una ventana real de Chromium para que resuelvas el CAPTCHA y lances la
busqueda tu mismo; el script espera, extrae todas las paginas de resultados
(el portal pagina de a 20, ej. "Procesos del 1 al 20 de 169"), incluyendo el
enlace directo de cada proceso (columna `url`, tomado del `href` del codigo
en la tabla del portal), y las guarda en la base de datos.

```bash
.venv/Scripts/python.exe scripts/scrape_portal.py [--espera SEGUNDOS] [--palabra-clave TEXTO]
```

- `--espera` (por defecto 90): segundos maximos que espera el script a que
  aparezcan resultados (continua antes si los detecta), para darte tiempo
  de leer el CAPTCHA, llenar los filtros y presionar "Buscar" en el propio
  sitio.
- El script lee automaticamente lo que escribiste en el campo "Palabras
  claves" del formulario del portal y lo guarda en la columna
  `palabra_clave` de todos los procesos importados en esa ejecucion (no
  hace falta indicarlo por linea de comandos). `--palabra-clave TEXTO`
  sigue disponible para forzar un valor especifico si la lectura
  automatica no encuentra nada (p.ej. si no escribiste ninguna palabra
  clave y buscaste solo por fecha/entidad).
- Cada ejecucion hace **una sola busqueda**. El portal solo permite un rango
  de fechas de 6 meses antes y 15 dias despues de la fecha de publicacion,
  asi que para cubrir varios periodos o palabras clave hay que ejecutar el
  script varias veces (uno por periodo/palabra clave).
- No pregunta si quieres continuar durante la ejecucion: la terminal desde
  la que se lanza normalmente pierde la entrada estandar interactiva cuando
  el proceso tarda mas de ~2 minutos, y cualquier pregunta por teclado
  fallaria con `EOFError`.
- Si el script no logra reconocer la tabla de resultados, guarda el HTML de
  la pagina en `debug_sin_tabla.html` (raiz del proyecto) para poder
  diagnosticar el problema.

**Importante:** este script abre una ventana visible del navegador, por lo
que debe ejecutarse desde tu propia terminal (no desde un proceso en segundo
plano sin acceso a tu escritorio).
