---
name: security-guard
description: Reglas estrictas de seguridad para scripts Python, API FastAPI y UI Streamlit de este proyecto. Úsala al escribir o revisar código que toque SQL, HTML/unsafe_allow_html, archivos subidos, rutas, subprocesos, secretos, inputs con formato de Ecuador (RUC, cédula, montos, fechas, CPC) o manejo de errores.
---

# security-guard

Reglas obligatorias para todo código nuevo o modificado. Si una regla choca con una petición del usuario, avisa y propone la alternativa segura antes de implementar.

Identificadores, comentarios y mensajes en español.

## 1. Inyección SQL (SQLite, `src/database.py`)

- **Siempre consultas parametrizadas**: `cursor.execute("... WHERE ruc = ?", (ruc,))`. Prohibido f-strings, `%`, `.format()` o concatenación con datos externos.
- Nombres de tabla/columna u `ORDER BY` dinámicos: solo desde una **lista blanca** fija (`dict`/`frozenset`), nunca desde el input.
- `LIKE`: escapa `%`, `_` y `\` del input y usa `ESCAPE '\'`.
- Listas con `IN`: genera los `?` según la longitud (`",".join("?" * len(xs))`), nunca interpoles valores.
- Una sola sentencia por `execute`; no uses `executescript` con datos externos.
- Cuidado con `create_function` y PRAGMA: no pasar input del usuario.

## 2. Inyección en la UI (HTML, XSS, Streamlit)

- `st.markdown(..., unsafe_allow_html=True)` **solo con HTML propio**. Todo dato dinámico (nombres de entidad, objetos de contratación, textos de borradores, valores de CSV/Excel/scraping) se escapa antes con `html.escape(str(valor), quote=True)`.
- Prefiere componentes nativos (`st.dataframe`, `st.metric`, `st.text`) cuando no haga falta HTML.
- Nunca inyectar datos externos dentro de `<style>`, `<script>`, atributos `href`/`src`/`style` ni `on*=`. URLs: validar esquema `http`/`https`.
- Vista previa HTML de Especificaciones Técnicas: escapar cada campo del borrador antes de armar el HTML.
- Inyección de fórmulas al exportar CSV/Excel: si una celda de texto empieza con `=`, `+`, `-`, `@`, `\t` o `\r`, antepón `'`.
- `.docx` (`python-docx`): insertar como texto (`add_run`), nunca interpretar markup; eliminar caracteres de control XML (`\x00-\x08\x0b\x0c\x0e-\x1f`).

## 3. Inputs con formato de Ecuador: normalizar y validar

Sanitiza en el borde (UI, importadores, API/Pydantic) y **rechaza** lo inválido, no lo "arregles" en silencio.

- **RUC**: solo dígitos, 13 caracteres, termina en `001` (o sufijo válido), provincia 01–24 o 30, tercer dígito 0–6 o 9, y verifica dígito verificador (módulo 10 para personas naturales, módulo 11 para sociedades privadas y públicas).
- **Cédula**: 10 dígitos, provincia 01–24 o 30, tercer dígito < 6, dígito verificador módulo 10.
- **Montos**: formato Ecuador (`1.234,56`) o `1234.56`. Usa `Decimal`, nunca `float`, para dinero. Rechaza `NaN`, `inf`, negativos donde no apliquen, notación científica y más de 2 decimales. Reutiliza `scripts/formato_ec.py`; no escribas parsers ad hoc.
- **Fechas**: parsear con formato explícito (`%d/%m/%Y` o ISO `%Y-%m-%d`), nunca `dateutil` permisivo con input libre. Validar rangos razonables.
- **Códigos CPC**: solo dígitos, longitud esperada (nivel 9), y comprobar existencia contra `data/cpc_n9.csv`.
- **Códigos de proceso SERCOP**: regex estricta acotada (ej. `^[A-Z0-9-]{5,60}$`) y longitud máxima.
- **Texto libre**: `strip()`, normalizar Unicode (`unicodedata.normalize("NFC", ...)`), eliminar caracteres de control, límite de longitud por campo, y conservar `ñ`/tildes (no filtrar por ASCII).
- Validación en **dos capas**: UI (feedback inmediato) y servidor (Pydantic en `src/models.py` con `Field(max_length=...)`, `pattern=`, validadores). Nunca confiar solo en la UI.

## 4. Archivos subidos, rutas y subprocesos

- Uploads (`.xlsx`, `.csv`, `.txt`, PDF): lista blanca de extensiones, **límite de tamaño** y de filas, nunca ejecutar ni evaluar contenido. Usar `scripts/lectura_archivos_tabulares.py`.
- Prohibido `eval`, `exec`, `pickle.load`, `yaml.load` sin `safe_load`, `os.system` y `subprocess(..., shell=True)` con datos externos. Subprocesos: lista de argumentos, `shell=False`, timeout.
- Rutas: construir con `pathlib`, resolver con `.resolve()` y comprobar que queda **dentro** del directorio permitido (anti `../`). Nombres de archivo del usuario: `Path(nombre).name` y caracteres seguros; nunca usarlos para escribir en cualquier ruta.
- XML/DOCX/PDF externos: no resolver entidades externas; tratar como no confiables.

## 5. Secretos y autenticación

- Secretos solo desde `.env`/variables de entorno: `API_KEY`, `ANTHROPIC_API_KEY`, `APP_USUARIO`, `APP_CLAVE`. Nunca en código, tests, logs, mensajes de error ni commits.
- Comparar credenciales con `secrets.compare_digest`. Mantener **fail-closed**: si falta la variable, se deniega.
- No imprimir ni registrar cabeceras `Authorization`/`X-API-Key`, claves ni contenido de borradores completos.
- No bajar la verificación TLS (`verify=False`). Mantener `truststore.inject_into_ssl()` en `importador_parametros.py`.
- `API_URL` y `RAG_CONTRATACION_URL`: solo configurables por entorno, nunca desde input del usuario (anti SSRF).
- Respetar `CLAUDE.local.md`: no modificar ni subir `data/*.db` ni `capturas/`, y no cambiar `scrape_portal.py` a `headless=True`.

## 6. Manejo seguro de errores

- Al usuario: mensajes **genéricos y accionables** ("No se pudo guardar el borrador. Intenta de nuevo."). Nunca mostrar trazas, rutas, SQL, nombres de tabla ni claves.
- Al log: detalle técnico con `logging` (`logger.exception(...)`), sin datos sensibles.
- Prohibido `except:` desnudo y `except Exception: pass`. Captura excepciones concretas; si degradas (como `explicar_desierta()` que devuelve `None`), deja registro.
- API FastAPI: `HTTPException` con `detail` genérico; 401/403/404/422 coherentes; no filtrar si un recurso existe cuando no corresponda. `debug=False` en producción.
- `requests`: siempre `timeout=`, controlar `RequestException`, no reintentar sin límite. Validar el JSON recibido antes de usarlo.
- Transacciones: `with conn:` para commit/rollback; cerrar conexiones; no dejar el estado a medias tras un fallo.
- Fallar cerrado: ante duda de validación o autorización, denegar.

## 7. Dependencias y entorno

- No añadir dependencias sin necesidad. Recuerda que `requirements.txt` es UTF-16: preservar la codificación.
- Fijar versiones razonables y revisar avisos conocidos (`pip-audit` si está disponible).
- No ejecutar código descargado; archivos descargados son datos no confiables.

## 8. Flujo al aplicar la skill

1. Identifica los **puntos de entrada** del cambio (campos de UI, archivos, parámetros de API, respuestas de scraping/HTTP).
2. Para cada uno: ¿se valida, se normaliza, se escapa en la salida?
3. Revisa SQL, HTML, rutas y subprocesos con los apartados 1, 2 y 4.
4. Añade pruebas en `tests/` para entradas hostiles: comillas y `'; DROP TABLE`, `<script>`, `../`, RUC/cédula con dígito verificador incorrecto, montos `1e999`/`NaN`, cadenas gigantes, caracteres de control.
5. Ejecuta `.venv/Scripts/python.exe -m pytest -q` y `ruff check .`.
6. Informa al usuario de los riesgos encontrados y lo que se corrigió.

## 9. Lista de comprobación final

- [ ] Todo SQL parametrizado o con lista blanca
- [ ] Todo dato dinámico en HTML pasa por `html.escape`
- [ ] RUC, cédula, montos, fechas y CPC validados en UI **y** servidor
- [ ] Uploads con extensión, tamaño y filas limitados
- [ ] Sin `eval`/`exec`/`shell=True`/`pickle` con datos externos
- [ ] Rutas confinadas al directorio permitido
- [ ] Secretos solo en entorno, comparados con `compare_digest`
- [ ] Errores al usuario genéricos; detalle solo en logs
- [ ] `timeout` en toda llamada HTTP
- [ ] Pruebas con entradas hostiles añadidas
