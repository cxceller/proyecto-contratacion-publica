---
name: frontend-design
description: Directrices de diseño de interfaz para la app Streamlit (app_ui.py, ui/, pages/). Úsala en toda tarea de maquetación, estilos, layout o componentes visuales para lograr un diseño moderno, premium y consistente, con micro-interacciones y buenas prácticas de UI.
---

# frontend-design

Guía para cualquier cambio visual en la UI Streamlit de este proyecto. Objetivo: que la interfaz se vea cuidada y profesional, no un formulario por defecto de Streamlit.

Todo identificador, comentario y texto de interfaz va en español.

## 1. Antes de tocar nada

- Revisa el estilo existente: el bloque CSS neumorfista inyectado en `app_ui.py` y las constantes de `ui/tema.py` (`COLOR_*`, `PALETA_DATOS`). **No lo rompas**; extiéndelo.
- Reutiliza `ui/componentes.py` antes de crear un widget nuevo. Si un widget se usa en más de una página, ponlo ahí.
- Los colores, radios, sombras y espaciados nuevos se definen como constantes o variables CSS (`:root { --... }`), nunca como valores sueltos repetidos.
- `pages/Reportes.py` / `ui/reportes.py` duplican a propósito el CSS del sidebar; si cambias el sidebar, actualiza ambos.

## 2. Principios de diseño premium

- **Jerarquía visual clara**: un solo foco por vista. Títulos con peso y tamaño contrastados, texto secundario atenuado, acciones primarias destacadas y secundarias discretas.
- **Espaciado generoso y consistente**: escala de 4/8 px (4, 8, 12, 16, 24, 32, 48). Evita bloques apretados y márgenes arbitrarios.
- **Paleta restringida**: 1 color de acento, neutros bien graduados, y colores semánticos solo para estado (éxito, alerta, error). Contraste mínimo WCAG AA (4.5:1 en texto).
- **Tipografía**: máximo 2 familias (una para títulos, una para cuerpo, o una sola). Usa cifras tabulares (`font-variant-numeric: tabular-nums`) en tablas y KPIs. Formatea números/moneda con `scripts/formato_ec.py`.
- **Superficies**: tarjetas con radio coherente (12–16 px), sombras suaves en capas en vez de bordes duros, y separación por espacio antes que por líneas.
- **Evita lo genérico**: nada de tablas crudas sin estilo, emojis como único icono, ni columnas de widgets alineadas al azar. Agrupa en tarjetas, usa KPIs, etiquetas de estado (badges) y estados vacíos con mensaje útil.

## 3. Micro-interacciones (cuando aporten)

- Transiciones de 150–250 ms con `ease-out` en hover, foco y pulsado (`transition: transform, box-shadow, background-color`).
- Hover en tarjetas y botones: elevación sutil (`translateY(-1px)` + sombra), nunca saltos grandes.
- Estado `:active` con ligera compresión (`scale(0.98)`).
- Foco visible y accesible (`:focus-visible` con anillo del color de acento); nunca `outline: none` sin reemplazo.
- Feedback inmediato: `st.spinner`/`st.status` en operaciones largas, `st.toast` para confirmaciones, mensajes de error con acción de reintento.
- Animaciones de entrada discretas (fade/slide de 200–300 ms) solo en contenido que aparece; respeta `@media (prefers-reduced-motion: reduce)` desactivándolas.
- Nada de animaciones decorativas continuas ni que bloqueen la interacción.

## 4. Buenas prácticas de UI

- **Estados completos**: cada componente de datos debe resolver carga, vacío, error y éxito.
- **Formularios**: etiquetas claras, ayuda contextual (`help=`), validación en línea con mensajes concretos, botón primario único y deshabilitado mientras haya errores bloqueantes.
- **Tablas y datos**: alineación numérica a la derecha, texto a la izquierda, encabezados fijos si hay scroll, formato Ecuador (coma decimal, `$`), colores de datos tomados de `PALETA_DATOS`.
- **Gráficos**: títulos descriptivos, ejes legibles, sin ruido (menos líneas de cuadrícula), colores accesibles y no solo diferenciados por tono.
- **Navegación**: la actual siempre indicada; no más de dos niveles; sidebar coherente entre `app_ui.py` y `/Reportes`.
- **Responsive**: probar en ancho estrecho; evitar anchos fijos en px para contenedores, preferir `%`, `minmax()`, `clamp()`.
- **Accesibilidad**: no depender solo del color, textos alternativos, áreas clicables ≥ 40 px, orden de tabulación lógico.
- **Rendimiento**: no inyectar CSS repetidamente en cada rerun costoso; una sola llamada a `st.markdown(..., unsafe_allow_html=True)` por bloque de estilos. Respetar el caché de `services/sercop.py`.
- Cuidado con Streamlit: sus clases internas (`.st-emotion-cache-*`) cambian entre versiones. Prefiere selectores `data-testid` o `[class*="..."]` estables y comenta por qué.
- No reintroducir la traducción automática del navegador sobre iconos (ver commit `f0d85a5`).

## 5. Flujo de trabajo

1. Describe en una o dos líneas la intención visual del cambio (qué jerarquía, qué acento).
2. Implementa en el módulo correcto (`ui/` para dominios y componentes; `app_ui.py` solo para el Dashboard y estilos globales).
3. Verifica en el navegador con `iniciar_sistema.bat` o la skill `run-app`: modo normal, estrecho, estados vacío/error.
4. Ejecuta `.venv/Scripts/python.exe -m pytest -q` y `ruff check .` sobre lo modificado.
5. Resume al usuario qué cambió visualmente y qué decisiones tomaste.

## 6. Lista de comprobación final

- [ ] Coherente con el neumorfismo y la paleta existentes
- [ ] Espaciado en escala, sin valores mágicos repetidos
- [ ] Hover / foco / activo definidos y con transición
- [ ] `prefers-reduced-motion` respetado
- [ ] Estados de carga, vacío y error cubiertos
- [ ] Contraste AA y foco visible
- [ ] Textos y comentarios en español
- [ ] Sin romper `/Reportes` ni el sidebar duplicado
