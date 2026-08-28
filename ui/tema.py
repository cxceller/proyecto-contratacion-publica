"""Constantes de color/paleta compartidas por app_ui.py y ui/especificaciones_tecnicas.py
-- separadas aca (P0-1 del plan de mejoras) para que ninguno de los dos
modulos tenga que importar del otro solo para acceder a un color."""

# Panel lateral de navegacion (estilo ERP: fondo oscuro, etiqueta de
# seccion con acento de color, items con icono + texto claro).
COLOR_SIDEBAR_FONDO = "#1E293B"
COLOR_SIDEBAR_TEXTO = "#CBD5E1"
COLOR_SIDEBAR_TEXTO_ACTIVO = "#FFFFFF"
COLOR_SIDEBAR_ACENTO = "#2a78d6"  # azul primario (= primaryColor en .streamlit/config.toml), acento de marca/item activo

# Paleta general de la interfaz (fuera de graficos): azul primario para
# botones de accion primaria (type="primary", ya configurado como
# primaryColor en .streamlit/config.toml) -- el resto de la UI usa estos
# tonos neutros. COLOR_PELIGRO es el rojo critico de la paleta de estados
# (ver ICONOS_ESTADO), exclusivo aca para acciones destructivas (Vaciar
# Base de Datos), para que nunca se confunda con una accion primaria
# normal (Generar Reporte, Guardar Items, etc.).
COLOR_PELIGRO = "#d03b3b"
COLOR_NEUTRO_BORDE = "#E2E8F0"
COLOR_NEUTRO_TEXTO_SUAVE = "#64748B"

# Paleta semantica de estados: unica fuente de verdad para "ok"/"aviso"/
# "critico" en toda la app (ICONOS_ESTADO reusa estos 3 tonos exactos, no
# colores sueltos por estado) -- siempre junto a icono + etiqueta, nunca
# color solo, para no depender del color para transmitir significado.
COLOR_ESTADO_OK = "#0ca30c"
COLOR_ESTADO_AVISO = "#fab219"
COLOR_ESTADO_CRITICO = "#d03b3b"

# Paleta de datos del dashboard (graficos categoricos con muchos segmentos:
# treemaps, Gantt por estado) -- familia de azules derivada del azul
# primario (#2a78d6 = primaryColor), en vez de colores sueltos sin relacion
# entre si, para que ningun grafico "compita" visualmente con el resto de
# la app. Sigue siendo ciclica (color_discrete_sequence): con mas
# categorias que colores, Plotly repite desde el principio.
PALETA_DATOS = [
    "#2a78d6", "#0f3d75", "#6fa8dc", "#164a8c",
    "#9cc2ef", "#1a5aa8", "#4a90d9", "#cfe0f5",
]
COLOR_LIENZO = "#fcfcfb"  # plot_bgcolor / paper_bgcolor: mismo tono que
                          # secondaryBackgroundColor (.streamlit/config.toml),
                          # fijo independiente del tema claro/oscuro de Streamlit
COLOR_GRID = "#e1e0d9"  # gridlines neutras, mismo calido que el fondo
COLOR_AXIS = "#0b0b0b"  # linea solida de eje ("trazo de tinta"), = textColor
COLOR_TEXTO_EJE = "#0b0b0b"  # texto de ejes/fuente general, = textColor (.streamlit/config.toml)

# Patron "barra lider destacada" compartido por los graficos de ranking
# (render_grafico_mensual, render_grafico_provincia, render_grafico_
# comparativo): todas las barras en azul suave (el color no codifica
# categoria, solo son "datos"), salvo la de mayor valor, que se resalta en
# naranja de acento -- el unico uso de naranja fuera de una alerta.
COLOR_BARRA_DATO = "#cfe0f5"
COLOR_BARRA_DESTACADA = "#eb6834"

# Altura minima comun a los TRES tipos de tarjeta KPI (P1-6 del plan de
# mejoras): simple (_tarjeta_kpi_html), con sparkline
# (_inyectar_estilos_kpi_tendencia) y gauge (_inyectar_estilos_gauge_ahorro).
# Antes cada una tenia su propia altura (8.5rem / sin min-height, crecia
# con el sparkline / sin min-height tampoco) y quedaban desalineadas en la
# misma fila -- una sola constante evita que vuelvan a divergir.
ALTURA_KPI_REM = 11.5
