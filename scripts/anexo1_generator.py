"""Genera el documento "ANEXO 1 - ESPECIFICACIONES TECNICAS PARA LOS
PROCESOS DE BIENES" de la M.I. Municipalidad de Guayaquil, replicando el
formato exacto de un modelo Word de referencia
(Especificaciones_tecnicas_modelo.docx):

- Encabezado y pie de pagina institucionales fijos (banner con el logo y
  la barra tricolor decorativa, y la barra de contacto), como imagenes
  ancladas -- no editables por el usuario, igual que en el modelo.
- Caja de titulo (4 lineas, Arial 13 negrita, centrada): nombre del
  Anexo, titulo del proceso, coordinacion/area responsable, y una linea
  final de texto libre resaltada en amarillo.
- Tabla principal de items: por cada item se repite un bloque de 5 filas
  (encabezado de 8 columnas, fila de datos, fila divisora "PARAMETROS /
  ESPECIFICACIONES TECNICAS", fila de especificaciones tecnicas con
  subtitulo resaltado en verde + subtabla de parametros nombre/valor, y
  una fila vacia de separacion) -- asi esta estructurado el modelo real,
  con el encabezado de columnas repetido antes de cada item en vez de
  una unica vez al inicio de toda la tabla.
"""
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Length, Pt

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
IMAGEN_ENCABEZADO = ASSETS_DIR / "mimg_header.jpg"
IMAGEN_PIE_PAGINA = ASSETS_DIR / "mimg_footer.jpg"

FUENTE = "Arial"
TAMANO_TITULO_PT = 13
TAMANO_ENCABEZADO_TABLA_PT = 9
TAMANO_DATOS_TABLA_PT = 8
TAMANO_DIVISOR_PT = 10
TAMANO_SUBTITULO_PT = 9
TAMANO_PARAMETRO_PT = 9

COLOR_FONDO_ENCABEZADO = "F2F2F2"

# Medidas replicadas del modelo real (ver investigacion: tblW/tblInd/
# gridCol en twips, convertidos aqui a cm -- 1 twip = 1/1440 in,
# 1 in = 2.54 cm).
_TWIPS_A_CM = 2.54 / 1440
ANCHO_TABLA_CM = 11761 * _TWIPS_A_CM
INDENTACION_TABLA_CM = -1568 * _TWIPS_A_CM
ANCHOS_COLUMNAS_CM = [
    1979 * _TWIPS_A_CM,  # ITEM
    1896 * _TWIPS_A_CM,  # DESCRIPCION
    1161 * _TWIPS_A_CM,  # Unidad de Medida
    1432 * _TWIPS_A_CM,  # CANTIDAD SOLICITADA
    1160 * _TWIPS_A_CM,  # VALOR UNITARIO
    963 * _TWIPS_A_CM,   # VALOR TOTAL
    1751 * _TWIPS_A_CM,  # Descripcion del CPC
    1276 * _TWIPS_A_CM,  # NUMERO CPC
]
ENCABEZADOS_COLUMNAS = [
    "ÍTEM",
    "DESCRIPCIÓN",
    "Unidad de Medida",
    "CANTIDAD SOLICITADA",
    "VALOR UNITARIO",
    "VALOR TOTAL",
    "Descripción del CPC",
    "NÚMERO CPC",
]
ALINEACIONES_COLUMNAS = [
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.JUSTIFY,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.CENTER,
    WD_ALIGN_PARAGRAPH.JUSTIFY,
    WD_ALIGN_PARAGRAPH.CENTER,
]


def _aplicar_fuente(run, tamano_pt: float, negrita: bool = True, resaltado=None) -> None:
    run.font.name = FUENTE
    run.font.size = Pt(tamano_pt)
    run.font.bold = negrita
    r_fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    r_fonts.set(qn("w:eastAsia"), FUENTE)
    if resaltado is not None:
        run.font.highlight_color = resaltado


def _sombrear_celda(cell, color_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def _configurar_propiedades_tabla_items(tabla) -> None:
    """Mismo ancho preferido y sangria negativa que la tabla de items del
    modelo real (se sale de los margenes de pagina, ver investigacion en
    la conversacion): python-docx no expone `tblW`/`tblInd` via su API
    publica, se arman a mano en <w:tblPr>."""
    tabla.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = tabla._tbl.tblPr

    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(Cm(ANCHO_TABLA_CM).twips))
    tbl_pr.append(tbl_w)

    tbl_ind = OxmlElement("w:tblInd")
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), str(Cm(INDENTACION_TABLA_CM).twips))
    tbl_pr.append(tbl_ind)


def _fijar_anchos_fila(celdas, anchos: list[Length]) -> None:
    for celda, ancho in zip(celdas, anchos):
        # python-docx solo respeta table.columns[i].width de forma
        # confiable si TAMBIEN se fija el ancho de cada celda individual
        # de esa columna (gotcha conocido de la libreria/Word).
        celda.width = ancho
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _configurar_encabezado_pie(documento: Document) -> None:
    """Banner de encabezado (logo + barra tricolor) y barra de contacto
    de pie de pagina, como imagenes fijas -- igual que el modelo, no son
    campos editables por el usuario."""
    seccion = documento.sections[0]
    seccion.header_distance = Cm(0.3)
    seccion.footer_distance = Cm(1.25)

    parrafo_encabezado = seccion.header.paragraphs[0]
    parrafo_encabezado.alignment = WD_ALIGN_PARAGRAPH.CENTER
    parrafo_encabezado.add_run().add_picture(str(IMAGEN_ENCABEZADO), width=Cm(19))

    parrafo_pie = seccion.footer.paragraphs[0]
    parrafo_pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
    parrafo_pie.add_run().add_picture(str(IMAGEN_PIE_PAGINA), width=Cm(17))


def _agregar_caja_titulo(
    documento: Document, nombre_anexo: str, titulo_proceso: str, coordinacion: str, texto_libre: str
) -> None:
    tabla = documento.add_table(rows=4, cols=1)
    tabla.style = "Table Grid"
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(Cm(ANCHO_TABLA_CM).twips))
    tabla._tbl.tblPr.append(tbl_w)

    textos = [nombre_anexo, titulo_proceso, coordinacion]
    for fila, texto in zip(tabla.rows[:3], textos):
        celda = fila.cells[0]
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_TITULO_PT)

    celda_libre = tabla.rows[3].cells[0]
    celda_libre.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    parrafo_libre = celda_libre.paragraphs[0]
    parrafo_libre.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_libre = parrafo_libre.add_run(texto_libre)
    _aplicar_fuente(run_libre, TAMANO_TITULO_PT, resaltado=WD_COLOR_INDEX.YELLOW)


def _agregar_fila_encabezado_item(tabla, anchos: list[Length]) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    for celda, texto in zip(fila.cells, ENCABEZADOS_COLUMNAS):
        _sombrear_celda(celda, COLOR_FONDO_ENCABEZADO)
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_ENCABEZADO_TABLA_PT)


def _agregar_fila_datos_item(tabla, numero_item: int, item: dict, anchos: list[Length]) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    valores = [
        str(numero_item),
        item.get("descripcion", ""),
        item.get("unidad_medida", ""),
        item.get("cantidad_solicitada", ""),
        item.get("valor_unitario", ""),
        item.get("valor_total", ""),
        item.get("descripcion_cpc", ""),
        item.get("numero_cpc", ""),
    ]
    for celda, valor, alineacion in zip(fila.cells, valores, ALINEACIONES_COLUMNAS):
        parrafo = celda.paragraphs[0]
        parrafo.alignment = alineacion
        run = parrafo.add_run(str(valor))
        _aplicar_fuente(run, TAMANO_DATOS_TABLA_PT)


def _agregar_fila_divisor_especificaciones(tabla, anchos: list[Length]) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda_parametros = fila.cells[0]
    celda_specs = fila.cells[1]
    for celda_extra in fila.cells[2:]:
        celda_specs = celda_specs.merge(celda_extra)

    for celda, texto in ((celda_parametros, "PARÁMETROS"), (celda_specs, "ESPECIFICACIONES TÉCNICAS")):
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        parrafo = celda.paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        _aplicar_fuente(run, TAMANO_DIVISOR_PT)


def _agregar_fila_especificaciones_tecnicas(
    tabla, subtitulo: str, parametros: list[dict], anchos: list[Length]
) -> None:
    fila = tabla.add_row()
    _fijar_anchos_fila(fila.cells, anchos)
    celda_label = fila.cells[0]
    celda_contenido = fila.cells[1]
    for celda_extra in fila.cells[2:]:
        celda_contenido = celda_contenido.merge(celda_extra)

    celda_label.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    parrafo_label = celda_label.paragraphs[0]
    parrafo_label.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_desc = parrafo_label.add_run("DESCRIPCIÓN")
    _aplicar_fuente(run_desc, TAMANO_DIVISOR_PT)
    parrafo_label.add_run().add_break()
    run_mat = parrafo_label.add_run("MATERIAL")
    _aplicar_fuente(run_mat, TAMANO_DIVISOR_PT)

    parrafo_subtitulo = celda_contenido.paragraphs[0]
    run_subtitulo = parrafo_subtitulo.add_run(subtitulo)
    _aplicar_fuente(run_subtitulo, TAMANO_SUBTITULO_PT, resaltado=WD_COLOR_INDEX.BRIGHT_GREEN)

    tabla_specs = celda_contenido.add_table(rows=0, cols=2)
    tabla_specs.style = "Table Grid"
    for parametro in parametros:
        fila_parametro = tabla_specs.add_row()
        run_nombre = fila_parametro.cells[0].paragraphs[0].add_run(parametro.get("nombre", ""))
        _aplicar_fuente(run_nombre, TAMANO_PARAMETRO_PT, negrita=True)
        run_valor = fila_parametro.cells[1].paragraphs[0].add_run(parametro.get("valor", ""))
        _aplicar_fuente(run_valor, TAMANO_PARAMETRO_PT, negrita=False)


def generar_anexo1(datos: dict, ruta_salida) -> Path:
    """`datos` = {
        "nombre_anexo": str, "titulo_proceso": str, "coordinacion": str,
        "texto_libre": str,
        "items": [
            {"descripcion": str, "unidad_medida": str,
             "cantidad_solicitada": str, "valor_unitario": str,
             "valor_total": str, "descripcion_cpc": str,
             "numero_cpc": str, "subtitulo_specs": str,
             "parametros": [{"nombre": str, "valor": str}, ...]},
            ...
        ],
    }"""
    documento = Document()
    _configurar_encabezado_pie(documento)
    _agregar_caja_titulo(
        documento,
        datos.get("nombre_anexo", ""),
        datos.get("titulo_proceso", ""),
        datos.get("coordinacion", ""),
        datos.get("texto_libre", ""),
    )
    documento.add_paragraph()

    tabla = documento.add_table(rows=0, cols=len(ENCABEZADOS_COLUMNAS))
    tabla.style = "Table Grid"
    tabla.autofit = False
    _configurar_propiedades_tabla_items(tabla)
    anchos = [Cm(v) for v in ANCHOS_COLUMNAS_CM]

    for numero, item in enumerate(datos.get("items", []), start=1):
        _agregar_fila_encabezado_item(tabla, anchos)
        _agregar_fila_datos_item(tabla, numero, item, anchos)
        _agregar_fila_divisor_especificaciones(tabla, anchos)
        _agregar_fila_especificaciones_tecnicas(
            tabla, item.get("subtitulo_specs", ""), item.get("parametros", []), anchos
        )
        tabla.add_row()  # fila vacia de separacion, igual que en el modelo

    ruta_salida = Path(ruta_salida)
    documento.save(str(ruta_salida))
    return ruta_salida
