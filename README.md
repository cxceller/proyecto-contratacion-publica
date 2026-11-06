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
- Por cada pagina de resultados con datos, guarda una captura de pantalla
  completa (`full_page=True`, sin cortes) en `capturas/`, con nombre
  `[palabra_clave]_[lote_id]_pag_[numero].png`
  (ej. `repotenciacion_2026-07-28T11-07-02_pag_1.png`). El `lote_id`
  identifica de forma unica esta ejecucion (misma columna `lote_id` que se
  guarda en la base de datos para cada proceso importado), asi que dos
  busquedas de la misma palabra clave el mismo dia no se sobrescriben las
  capturas entre si.

**Importante:** este script abre una ventana visible del navegador, por lo
que debe ejecutarse desde tu propia terminal (no desde un proceso en segundo
plano sin acceso a tu escritorio).

## Seguridad

### Login (toda la app)

Todas las páginas (Dashboard, Procesos, Municipalidad, Configuración y `/Reportes`) exigen login.
Es *fail-closed*: sin `APP_USUARIO` y `APP_CLAVE_HASH` en `.env`, nadie entra.

1. Genera el hash argon2id de la clave (pide la clave sin mostrarla, mínimo 12 caracteres):

   ```bash
   .venv/Scripts/python.exe scripts/generar_hash_clave.py
   ```

2. Pega la línea `APP_CLAVE_HASH='...'` en `.env` (usa comillas simples: el hash contiene `$`) y borra `APP_CLAVE`
   (ya no se usa). Copia `.env.example` si partes de cero.

- **Bloqueo temporal creciente:** 5 fallos seguidos → 1 min, luego 5 min, luego 15 min (nunca permanente).
  Se guarda en `data/login_intentos.sqlite3` (o `LOGIN_STATE_PATH`), no en la sesión del navegador.
- **Sesión:** expira a los 30 min de inactividad. Cada pestaña nueva (por ejemplo `/Reportes`) es una sesión
  distinta de Streamlit y pide el login de nuevo.
- **Acciones destructivas:** el reset completo (`BORRAR`) y el borrado de borradores vuelven a pedir la clave aunque
  haya sesión, y dejan en el log una línea `AUDITORIA accion=... usuario=... resultado=...` (la hora la pone el logger).
- **Logs:** nivel con `LOG_LEVEL` (`DEBUG|INFO|WARNING|ERROR`). Nunca se registran claves ni hashes.

### Respaldo con IA de los importadores

Desactivado por defecto (`LLM_FALLBACK_ENABLED=false`): el contenido del archivo no sale a ningún servicio externo.
Si lo activas (`true`), la UI muestra un aviso antes de subir el archivo, se enmascaran cédulas, RUC, correos y teléfonos
reconocibles (los nombres de personas **no** se pueden detectar), se limita lo que se envía y la respuesta se valida con
Pydantic y se limpia (sin HTML ni caracteres de control).

### Cloud Run: comprobar que el servicio no es público

El login de la app **no sustituye** al control de acceso de la infraestructura. Comandos para verificar y corregir
(reemplaza `SERVICIO` y `REGION`):

```bash
# 1) ¿Quién puede invocar el servicio? Busca "allUsers" o "allAuthenticatedUsers" en la salida.
gcloud run services get-iam-policy SERVICIO --region REGION

# 2) Quitar el acceso público (ejecuta los dos si aparecen ambos).
gcloud run services remove-iam-policy-binding SERVICIO --region REGION \
  --member="allUsers" --role="roles/run.invoker"
gcloud run services remove-iam-policy-binding SERVICIO --region REGION \
  --member="allAuthenticatedUsers" --role="roles/run.invoker"

# 3) Exigir autenticación en el servicio (equivale a quitar el "allow unauthenticated").
gcloud run services update SERVICIO --region REGION --no-allow-unauthenticated

# 4) Dar acceso solo a quien corresponda (usuario o grupo).
gcloud run services add-iam-policy-binding SERVICIO --region REGION \
  --member="user:persona@dominio.com" --role="roles/run.invoker"

# 5) Verificar: sin token debe responder 403; con token, 200.
curl -s -o /dev/null -w "%{http_code}\n" https://URL-DEL-SERVICIO
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://URL-DEL-SERVICIO
```

La API (FastAPI) escucha solo en `127.0.0.1:8000` dentro del contenedor, y en producción (`K_SERVICE` o
`APP_ENV=production`) `/docs`, `/redoc` y `/openapi.json` están desactivados.

### Cloud Run: pasar `APP_CLAVE_HASH` con Secret Manager (solo referencia, no se ejecuta aquí)

El hash contiene `$`, así que **no** lo pases con `--set-env-vars` (el shell y gcloud lo interpretan): usa un secreto.
Reemplaza `PROYECTO`, `SERVICIO`, `REGION` y la cuenta de servicio con la que corre el servicio.

```bash
# 1) Crear el secreto con el hash (comillas simples; nunca la clave en texto plano).
gcloud secrets create sercop-app-clave-hash --replication-policy=automatic --project=PROYECTO
printf '%s' '$argon2id$v=19$m=65536,t=3,p=4$...' | \
  gcloud secrets versions add sercop-app-clave-hash --data-file=- --project=PROYECTO

# 2) Permitir que la cuenta de servicio del servicio lo lea (solo lectura de ese secreto).
gcloud secrets add-iam-policy-binding sercop-app-clave-hash --project=PROYECTO \
  --member="serviceAccount:CUENTA-DE-SERVICIO@PROYECTO.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 3) Exponerlo como variable de entorno del servicio (misma idea para API_KEY).
gcloud run services update SERVICIO --region REGION --project=PROYECTO \
  --update-secrets="APP_CLAVE_HASH=sercop-app-clave-hash:latest"
# APP_USUARIO no es secreto: --update-env-vars="APP_USUARIO=nombre"

# 4) Rotar la clave: generar un hash nuevo y agregar una versión; "latest" lo toma en el próximo arranque.
printf '%s' 'NUEVO_HASH' | gcloud secrets versions add sercop-app-clave-hash --data-file=- --project=PROYECTO
gcloud run services update SERVICIO --region REGION --project=PROYECTO --update-env-vars="ROTACION=$(date +%s)"
```

Notas: ver «Bloqueo de login: por instancia» más abajo.
Verifica el despliegue con `gcloud run services describe SERVICIO --region REGION --format="yaml(spec.template.spec.containers[0].env)"`
(los secretos aparecen como referencias `secretKeyRef`, nunca el valor).

### Respaldo y restauración del reset completo

Cada reset (Configuración → Zona de peligro) guarda antes `respaldos/<AAAAMMDD_HHMMSS>/` con `contrataciones.db`
(copia consistente, incluye lo que estaba en el `-wal`) y los `.docx` de `salidas/reportes/`. Para volver atrás
(**detén primero la app**, API y Streamlit):

```bash
.venv/Scripts/python.exe scripts/restaurar_respaldo.py --listar                  # respaldos disponibles
.venv/Scripts/python.exe scripts/restaurar_respaldo.py 20260101_120000           # solo informa, no modifica nada
.venv/Scripts/python.exe scripts/restaurar_respaldo.py 20260101_120000 --confirmar
```

Valida la ruta (solo carpetas dentro de `respaldos/`) y `PRAGMA integrity_check`; antes de aplicar guarda la BD actual en
`respaldos/pre_restauracion_<ts>/`. Restaura **toda** la base (los borradores creados después del respaldo se pierden; por
eso existe la copia previa) y copia los `.docx` que falten (`--sobrescribir-reportes` para pisar los existentes).
Las capturas (`capturas/`) no se respaldan en el reset: si marcaste borrarlas, hay que volver a generarlas.

### Respaldos del reset en Cloud Run (Cloud Storage)

En Cloud Run el disco del contenedor es efímero, así que cuando corre ahí (`K_SERVICE` definido) el reset **sube el
respaldo a Cloud Storage antes de borrar nada**: `gs://$SERCOP_DB_BUCKET/respaldos/<AAAAMMDD_HHMMSS>/contrataciones.db`
(y `reportes/*.docx`, si había). Cada archivo se verifica por checksum MD5; si la subida falla, el bucket no está
configurado o el checksum no coincide, el reset **aborta sin borrar nada** (la UI muestra «no se borró nada»; el detalle
técnico queda solo en el log). En local el reset sigue guardando solo en `respaldos/`.

- **Permisos:** la cuenta de servicio del servicio necesita crear, leer y listar objetos en ese bucket
  (por ejemplo `roles/storage.objectAdmin`, o `objectCreator` + `objectViewer`). Opcional: `SERCOP_RESPALDOS_PREFIX`
  (por defecto `respaldos/`) y `RESPALDOS_DIR` (carpeta temporal local, por defecto `/tmp/respaldos`).
- **Listar y restaurar desde el bucket** (desde un equipo con acceso al bucket; detén antes la app):

  ```bash
  export SERCOP_DB_BUCKET=nombre-del-bucket
  export GCS_ACCESS_TOKEN="$(gcloud auth print-access-token)"
  .venv/Scripts/python.exe scripts/restaurar_respaldo.py --origen gcs --listar
  .venv/Scripts/python.exe scripts/restaurar_respaldo.py --origen gcs 20260101_120000              # solo informa
  .venv/Scripts/python.exe scripts/restaurar_respaldo.py --origen gcs 20260101_120000 --confirmar
  ```

  Baja el respaldo, verifica sus checksums y restaura la BD **local** (guardando antes la actual en
  `respaldos/pre_restauracion_<ts>/`).
- **Devolver los datos a producción:** la BD de Cloud Run vive en `/tmp` de cada instancia y se repone desde el
  snapshot del bucket al arrancar. Para restaurar en producción, sube la BD restaurada como nuevo snapshot
  (`gsutil cp data/contrataciones.db gs://BUCKET/contrataciones.db`) y recicla las instancias
  (`gcloud run services update SERVICIO --region REGION --update-env-vars="ROTACION=$(date +%s)"`).

### Bloqueo de login: por instancia (límite conocido)

El contador de intentos fallidos se guarda en un SQLite **local a cada instancia** (junto a la BD, `/tmp` en Cloud Run).
Hoy es suficiente porque el acceso está protegido con IAP, que filtra antes de llegar a la app. **Si se quita IAP, o si
el servicio pasa a usar varias instancias (escalado > 1), el contador debe pasar a almacenamiento compartido**
(Firestore, Cloud SQL o Redis/Memorystore): de lo contrario un atacante obtiene 5 intentos por instancia y por ventana, y
el bloqueo se pierde al reciclarse la instancia. Hasta entonces, fija `--max-instances=1` o mantén IAP activo.

## HTTPS Load Balancer con IAP, cabeceras de seguridad y Cloud Armor (solo documentación)

> Esta sección **no se ejecuta desde el repo**: son los pasos para montar, delante de Cloud Run, un Application Load
> Balancer externo con IAP, cabeceras de respuesta y rate limiting. Sustituye `PROYECTO`, `REGION`, `SERVICIO`,
> `app.ejemplo.com` y los correos.

### 0. Cloud Run solo accesible por el Load Balancer

```bash
gcloud run services update SERVICIO --region REGION --project=PROYECTO \
  --ingress=internal-and-cloud-load-balancing --no-allow-unauthenticated
# Comprobar que no quedan allUsers/allAuthenticatedUsers (ver "Cloud Run: comprobar que el servicio no es público")
```

### 1. NEG serverless, backend service y balanceador

```bash
gcloud compute network-endpoint-groups create sercop-neg --region=REGION --project=PROYECTO \
  --network-endpoint-type=serverless --cloud-run-service=SERVICIO

gcloud compute backend-services create sercop-backend --global --project=PROYECTO \
  --load-balancing-scheme=EXTERNAL_MANAGED --protocol=HTTPS
gcloud compute backend-services add-backend sercop-backend --global --project=PROYECTO \
  --network-endpoint-group=sercop-neg --network-endpoint-group-region=REGION

gcloud compute addresses create sercop-ip --global --project=PROYECTO
gcloud compute ssl-certificates create sercop-cert --project=PROYECTO --domains=app.ejemplo.com --global
gcloud compute url-maps create sercop-map --project=PROYECTO --default-service=sercop-backend
gcloud compute target-https-proxies create sercop-proxy --project=PROYECTO \
  --url-map=sercop-map --ssl-certificates=sercop-cert
gcloud compute forwarding-rules create sercop-https --global --project=PROYECTO \
  --load-balancing-scheme=EXTERNAL_MANAGED --address=sercop-ip --target-https-proxy=sercop-proxy --ports=443
```

Apunta el DNS de `app.ejemplo.com` a la IP reservada. El WebSocket de Streamlit (`/_stcore/stream`) funciona por este
balanceador; si hay cortes, sube el timeout del backend (`gcloud compute backend-services update sercop-backend --global --timeout=3600`).

### 2. IAP delante del backend service

```bash
gcloud compute backend-services update sercop-backend --global --project=PROYECTO --iap=enabled
gcloud iap web add-iam-policy-binding --resource-type=backend-services --service=sercop-backend --project=PROYECTO \
  --member="user:persona@dominio.com" --role="roles/iap.httpsResourceAccessor"
```

(Requiere la pantalla de consentimiento OAuth del proyecto configurada.) IAP autentica antes de llegar a la app; el login de
la app sigue siendo una segunda capa.

### 3. Cabeceras de respuesta personalizadas

La CSP se **genera** con el repo (incluye los hashes SHA-256 de los scripts inline y el `connect-src` del WebSocket) y debe
**regenerarse cada vez que cambie la versión de Streamlit** o los scripts de `ui/componentes.py`:

```bash
CSP="$(.venv/Scripts/python.exe scripts/calcular_hashes_csp.py --dominio app.ejemplo.com --frame-ancestors self)"

gcloud compute backend-services update sercop-backend --global --project=PROYECTO \
  --custom-response-header="Content-Security-Policy: ${CSP}" \
  --custom-response-header="X-Content-Type-Options: nosniff" \
  --custom-response-header="Strict-Transport-Security: max-age=31536000; includeSubDomains" \
  --custom-response-header="Referrer-Policy: strict-origin-when-cross-origin" \
  --custom-response-header="Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), interest-cohort=()"
```

Qué dice la CSP y por qué (probada localmente, ver más abajo):

| Directiva | Valor | Motivo |
|---|---|---|
| `script-src` | `'self' 'wasm-unsafe-eval'` + hashes | Sin `'unsafe-inline'` ni `'unsafe-eval'`. Los hashes cubren los scripts inline de `index.html` de Streamlit y los 2 scripts de iframes invisibles; el cliente de Streamlit compila WebAssembly (protobuf). |
| `style-src` | `'self' 'unsafe-inline' https://fonts.googleapis.com` | Streamlit (emotion), Plotly y TinyMCE escriben estilos inline; la fuente Inter de `estilos_sercop.py` viene de Google Fonts. |
| `font-src` / `img-src` | `'self' data: …` / `'self' data: blob:` + CARTO | Fuentes de Google y de Material Symbols; imágenes pegadas en TinyMCE (`data:`); teselas del mapa. |
| `connect-src` | `'self' wss://DOMINIO` + `basemaps.cartocdn.com` | WebSocket de Streamlit y el mapa del Dashboard (estilo y teselas vectoriales de CARTO). |
| `worker-src` | `'self' blob:` | Web workers de Streamlit/Plotly. |
| `frame-src` | `'self' blob: data:` | Iframe del componente TinyMCE (mismo origen) y los `srcdoc` de `st.iframe`. |
| `object-src` / `base-uri` / `form-action` | `'none'` / `'self'` / `'self'` | Endurecimiento estándar. |
| `frame-ancestors` | `'self'` (o `'none'`, ver abajo) | Anticlickjacking: ningún otro sitio puede embeber la app. |

**`frame-ancestors 'none'` y el editor TinyMCE.** Streamlit carga el editor en un iframe **del mismo origen** (`/component/…`), y
`frame-ancestors 'none'` también bloquea ese iframe: el editor no aparece. Probado: hay dos opciones válidas.

1. **Sencilla (recomendada):** `frame-ancestors 'self'` en todo (`--frame-ancestors self`). Sigue impidiendo que *otros sitios*
   embeban la app; solo permite que la app se embeba a sí misma.
2. **Estricta:** mantener `'none'` (`--frame-ancestors none`) y crear un segundo backend service (`sercop-backend-componentes`,
   mismo NEG, con la CSP en `'self'`), enrutando solo `/component/*` a él con un `path-matcher` del URL map:
   `gcloud compute url-maps add-path-matcher sercop-map --default-service=sercop-backend --path-matcher-name=componentes --backend-service-path-rules="/component/*=sercop-backend-componentes"`.

Si más adelante empaquetas la fuente Inter y el mapa base en local, puedes quitar `fonts.googleapis.com`, `fonts.gstatic.com` y
CARTO de la política.

### 4. Cloud Armor: rate limiting por IP

```bash
gcloud compute security-policies create sercop-armor --project=PROYECTO --description="SERCOP: rate limiting por IP"

# 300 peticiones/minuto por IP; por encima, 429. (Una carga de página de Streamlit hace decenas de peticiones estáticas.)
gcloud compute security-policies rules create 1000 --security-policy=sercop-armor --project=PROYECTO \
  --expression="true" --action=throttle \
  --rate-limit-threshold-count=300 --rate-limit-threshold-interval-sec=60 \
  --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP

# Opcional: baneo temporal de las IPs que insisten tras superar el límite
gcloud compute security-policies rules create 900 --security-policy=sercop-armor --project=PROYECTO \
  --expression="true" --action=rate-based-ban \
  --rate-limit-threshold-count=900 --rate-limit-threshold-interval-sec=60 \
  --ban-duration-sec=600 --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP

gcloud compute backend-services update sercop-backend --global --project=PROYECTO --security-policy=sercop-armor
```

Límite importante: los intentos de contraseña viajan por el **WebSocket** (una única petición HTTP abierta), así que Cloud Armor
**no puede contar los intentos de login**. El freno real a la fuerza bruta es el bloqueo temporal de la app (ver «Bloqueo de
login») e IAP; Cloud Armor limita el volumen de conexiones y peticiones por IP.

### 5. Verificar

```bash
curl -sI https://app.ejemplo.com | grep -iE "content-security-policy|strict-transport|x-content-type|referrer-policy|permissions-policy"
```

Con IAP activo, sin sesión la respuesta es una redirección a Google: comprueba las cabeceras ya autenticado (herramientas del
navegador → Red → documento) o con un token de IAP.

### Prueba local de la CSP (lo que se comprobó antes de documentarla)

Un proxy de pruebas añadió estas mismas cabeceras a **todas** las respuestas (páginas y componentes) y se recorrió la app real
(Streamlit 1.67) con Chromium, registrando cada violación (`securitypolicyviolation`):

- WebSocket (login, navegación, reruns) ✔ · gráficos Plotly y el mapa de CARTO ✔ · `st.dataframe` ✔ · pestañas y expanders ✔
- Estilos inline de Streamlit (sidebar con degradado, tarjetas) ✔ · iframes invisibles `srcdoc` con sus scripts ✔
- Editor TinyMCE vendorizado, dentro de la app y suelto ✔ (con `frame-ancestors 'self'`, o `'none'` + excepción en `/component/`;
  con `'none'` en todo el editor no carga)
- **0 violaciones de CSP** y las 5 cabeceras presentes. Para conseguirlo: el script del componente TinyMCE se movió a
  `assets/tinymce_editor/editor.js` y los scripts de iframes invisibles son constantes hasheables (`ui/componentes.py`).
- En la consola aparece un `404` de «Download Button source»; ocurre **también sin CSP** (no está relacionado).
