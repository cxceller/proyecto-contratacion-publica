"""Ensambla un informe .docx (Word) que documenta las busquedas realizadas
en el portal de Compras Publicas (SERCOP) via scripts/scrape_portal.py.

Por cada palabra clave, el informe agrega:
1. Bloque de titulo (una vez), centrado, Tahoma 12 negrita, sin
   sombreado: "Proceso Régimen Común" y, debajo, "Palabra Clave: " + la
   palabra clave en rojo.
2. El rango de busqueda GLOBAL (una vez): "RANGO DE BUSQUEDA:
   [FECHA INICIO GLOBAL] A [FECHA FIN GLOBAL]" / "PALABRA CLAVE:
   [PALABRA CLAVE EN MAYUSCULAS]", con los meses en letras mayusculas en
   español, Tahoma 10, alineado a la izquierda, con negrita solo en la
   etiqueta ("RANGO DE BUSQUEDA:" / "PALABRA CLAVE") y no en el valor.
3. El mismo par de lineas repetido por cada bloque de 6 meses
   (semestre) dentro de ese rango global (ver
   scripts/reportes_capturas.py::rangos_semestrales), seguido de las
   capturas de pantalla que le correspondan a ese semestre por la fecha
   real de sus datos (ver scripts/reportes_capturas.py::lotes_de_capturas/
   asignar_lotes_a_semestres), con borde negro solido.
4. La declaracion "EXISTEN [N] PROCESOS LOS MISMOS QUE SERÁN ANALIZADOS."
5. Una unica tabla (fuente Tahoma, columnas de ancho fijo) con todos los
   procesos de esa palabra clave. La columna "Observaciones" lleva, si
   `llenar_observaciones` es True (default), `OBSERVACION_TEXTO` + el
   objeto del proceso completo en mayusculas (ver _observacion_partes).

Uso tipico (df ya cargado con las columnas del esquema de la BD: id,
codigo, entidad_contratante, objeto_proceso, estado, provincia_canton,
presupuesto_referencial, fecha_publicacion, palabra_clave, url --
ver src/database.py::get_contrataciones_para_reporte):

    from scripts.reportes_generator import generar_reporte

    generar_reporte(
        df=df,
        palabras_clave=["luminarias", "repotenciacion"],
        fecha_inicio_global="2025-07-01",
        fecha_fin_global="2026-06-30",
    )
"""
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Length, Pt, RGBColor
from dotenv import load_dotenv

from scripts.formato_ec import formatear_moneda_ec
from scripts.reportes_capturas import (
    asignar_lotes_a_semestres,
    dividir_imagen_si_no_cabe,
    lotes_de_capturas,
    rangos_semestrales,
)

load_dotenv()

# Carpeta donde se guardan las partes de una captura demasiado alta para
# una pagina (ver _agregar_captura). NUNCA la carpeta capturas/ (de solo
# lectura para este generador -- ver scripts/reportes_capturas.py).
DIRECTORIO_SALIDAS_CAPTURAS = Path(__file__).resolve().parent.parent / "salidas" / "capturas"

# Estilo del documento: tipografia general del cuerpo, de titulos y de
# la tabla, mas el borde de las capturas de pantalla.
FUENTE = "Tahoma"
TAMANO_CUERPO_PT = 10
TAMANO_TITULO_PT = 12
TAMANO_TABLA_PT = 6  # 5 o 6 pt son legibles en celdas compactas; 6 por legibilidad
TAMANO_OBSERVACIONES_PT = 8  # Observaciones ahora lleva el objeto completo -- 6pt es ilegible para una oracion larga
COLOR_BORDE_IMAGEN = "000000"
GROSOR_BORDE_IMAGEN_PT = 1.0

# Bloque de titulo ("Proceso Régimen Común" / "Palabra Clave: X"): unico
# lugar del documento con la palabra clave en rojo (en el resto del
# documento va en negro). Sin sombreado de parrafo.
COLOR_PALABRA_CLAVE_TITULO = RGBColor(0xFF, 0x00, 0x00)

# Numeros pequeños en letras, para "N (num_en_letras) años" en el parrafo
# introductorio; si el numero no esta en el diccionario, se muestra solo
# el numeral.
NUMEROS_EN_LETRAS = {
    1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco",
    6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez",
    11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince",
    16: "dieciséis", 17: "diecisiete", 18: "dieciocho", 19: "diecinueve", 20: "veinte",
}

# Propiedades de tabla pedidas explicitamente (vistas en el dialogo
# "Propiedades de tabla" de Word): sangria negativa (extiende la tabla
# mas alla del margen izquierdo normal) y alto minimo de fila.
INDENTACION_TABLA_CM = -2.51
ALTO_MINIMO_FILA_CM = 0.04

# Ancho FIJO de cada columna de la tabla, en cm (mismo orden que
# COLUMNAS_TABLA_REPORTE) -- medida exacta, no proporcional. La suma se
# mantiene igual a la original (21.06cm) a proposito: la tabla usa una
# sangria negativa (INDENTACION_TABLA_CM) calibrada para ese ancho total,
# asi que crecer la suma la haria caer fuera del borde derecho de la
# pagina -- Observaciones crece a costa de achicar el resto, no sumando.
ANCHOS_COLUMNAS_CM = [0.8, 1.8, 3.0, 3.56, 1.7, 1.7, 1.9, 1.6, 5.0]
ANCHO_TABLA_CM = sum(ANCHOS_COLUMNAS_CM)

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}

COLUMNAS_TABLA_REPORTE = [
    "N°", "Código", "Entidad Contratante", "Objeto del Proceso",
    "Estado del Proceso", "Provincia/Cantón",
    "Presupuesto Referencial Total(sin iva)", "Fecha de Publicación",
    "Observaciones",
]
INDICE_COLUMNA_OBSERVACIONES = COLUMNAS_TABLA_REPORTE.index("Observaciones")

# Texto fijo que antecede al objeto del proceso en la columna
# "Observaciones" (ver _observacion_partes). Configurable via
# OBSERVACION_TEXTO en .env sin tocar el codigo -- por ejemplo si cambia
# la redaccion estandar que pide el cliente.
OBSERVACION_TEXTO_DEFECTO = (
    "NO APLICA, ESTE PROCESO NO SE CONSIDERA POR TENER OBJETO DE CONTRATACIÓN "
    "DIFERENTE Y SER DE CARACTERÍSTICAS DIFERENTES A LO QUE SE REQUIERE ADQUIRIR - "
)
OBSERVACION_TEXTO = os.environ.get("OBSERVACION_TEXTO", OBSERVACION_TEXTO_DEFECTO)


def _normalizar_texto(texto) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto or ""))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


def _aplicar_fuente(run, tamano_pt: float, negrita: bool | None = None, fuente: str = FUENTE) -> None:
    """Fija fuente/tamano/negrita de un run. Ademas de `run.font.name`
    (que Word solo respeta para texto "ascii"/latino), setea tambien
    `w:eastAsia` en las propiedades del run: sin ese atributo, algunos
    renderizadores ignoran la fuente elegida."""
    run.font.name = fuente
    run.font.size = Pt(tamano_pt)
    if negrita is not None:
        run.font.bold = negrita
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:eastAsia"), fuente)


def _agregar_imagen_con_borde(
    documento: Document,
    ruta_imagen,
    ancho: Length,
    color_hex: str = COLOR_BORDE_IMAGEN,
    grosor_pt: float = GROSOR_BORDE_IMAGEN_PT,
):
    """Inserta una imagen envuelta en una tabla de 1x1, con borde de
    celda solido en los 4 lados (<w:tcBorders>) y sin margen interno."""
    tabla = documento.add_table(rows=1, cols=1)
    tabla.autofit = False
    tabla.alignment = WD_TABLE_ALIGNMENT.LEFT

    celda = tabla.cell(0, 0)
    celda.width = ancho
    tabla.columns[0].width = ancho

    tc_pr = celda._tc.get_or_add_tcPr()

    tc_borders = OxmlElement("w:tcBorders")
    for lado in ("top", "left", "bottom", "right"):
        borde = OxmlElement(f"w:{lado}")
        borde.set(qn("w:val"), "single")
        borde.set(qn("w:sz"), str(int(grosor_pt * 8)))  # w:sz: octavos de punto
        borde.set(qn("w:space"), "0")
        borde.set(qn("w:color"), color_hex)
        tc_borders.append(borde)
    tc_pr.append(tc_borders)

    tc_mar = OxmlElement("w:tcMar")
    for lado in ("top", "left", "bottom", "right"):
        margen = OxmlElement(f"w:{lado}")
        margen.set(qn("w:w"), "0")
        margen.set(qn("w:type"), "dxa")
        tc_mar.append(margen)
    tc_pr.append(tc_mar)

    parrafo = celda.paragraphs[0]
    parrafo.paragraph_format.space_before = Pt(0)
    parrafo.paragraph_format.space_after = Pt(0)
    parrafo.add_run().add_picture(str(ruta_imagen), width=ancho)
    return tabla


def _agregar_pie_parte(documento: Document, numero_captura: int, indice_parte: int, total_partes: int) -> None:
    parrafo = documento.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = parrafo.add_run(f"Captura {numero_captura} – parte {indice_parte} de {total_partes}")
    _aplicar_fuente(run, TAMANO_TABLA_PT, negrita=False)
    run.font.italic = True


def _agregar_captura(
    documento: Document,
    ruta_imagen: Path,
    ancho: Length,
    alto_util: Length,
    numero_captura: int,
    directorio_salidas_capturas: Path,
) -> None:
    """Inserta una captura de pantalla, dividiendola primero si no cabe
    entera en una pagina (ver scripts/reportes_capturas.py::dividir_imagen_si_no_cabe).

    Si cabe en una pagina, se inserta igual que siempre (sin salto de
    pagina ni pie). Si no cabe, cada parte va en su propia pagina con un
    pie "Captura N – parte i de M" debajo."""
    partes = dividir_imagen_si_no_cabe(ruta_imagen, ancho, alto_util, directorio_salidas_capturas)

    if len(partes) == 1 and partes[0] == ruta_imagen:
        _agregar_imagen_con_borde(documento, ruta_imagen, ancho)
        return

    total_partes = len(partes)
    for indice, parte in enumerate(partes, start=1):
        documento.add_page_break()
        _agregar_imagen_con_borde(documento, parte, ancho)
        _agregar_pie_parte(documento, numero_captura, indice, total_partes)


def _configurar_propiedades_tabla(tabla) -> None:
    """python-docx no expone tblW/tblInd via su API publica, asi que se
    arman a mano en <w:tblPr>."""
    tabla.alignment = WD_TABLE_ALIGNMENT.LEFT

    tbl_pr = tabla._tbl.tblPr
    ancho_twips = str(Cm(ANCHO_TABLA_CM).twips)

    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), ancho_twips)

    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), str(Cm(INDENTACION_TABLA_CM).twips))


def _configurar_propiedades_fila(fila, es_encabezado: bool = False) -> None:
    """El orden de insercion en <w:trPr> importa para el esquema OOXML
    (cantSplit, trHeight, tblHeader, en ese orden)."""
    tr_pr = fila._tr.get_or_add_trPr()

    cant_split = OxmlElement("w:cantSplit")
    cant_split.set(qn("w:val"), "0")  # 0 = permitir que la fila se divida entre paginas
    tr_pr.append(cant_split)

    fila.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    fila.height = Cm(ALTO_MINIMO_FILA_CM)

    if es_encabezado:
        tbl_header = OxmlElement("w:tblHeader")
        tbl_header.set(qn("w:val"), "1")
        tr_pr.append(tbl_header)


def _formatear_fecha_larga(valor, conector_anio: str = "de") -> str:
    """'2026-07-23' -> '23 de julio de 2026' (conector_anio='de') o
    '23 de julio del 2026' (conector_anio='del', para el parrafo
    introductorio)."""
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return str(valor)
    meses_por_numero = {v: k for k, v in MESES_ES.items()}
    return f"{fecha.day} de {meses_por_numero[fecha.month]} {conector_anio} {fecha.year}"


def _formatear_fecha_larga_mayusculas(valor) -> str:
    return _formatear_fecha_larga(valor, conector_anio="de").upper()


def _numero_en_letras(numero: int) -> str:
    return NUMEROS_EN_LETRAS.get(numero, str(numero))


def _anios_entre(fecha_inicio, fecha_fin) -> int:
    inicio = pd.to_datetime(fecha_inicio, errors="coerce")
    fin = pd.to_datetime(fecha_fin, errors="coerce")
    if pd.isna(inicio) or pd.isna(fin):
        return 1
    dias = (fin - inicio).days
    return max(1, round(dias / 365.25))


def _formatear_fecha_corta(valor) -> str:
    if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return str(valor)
    return fecha.strftime("%d/%m/%Y")


def _formatear_moneda(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return formatear_moneda_ec(valor)


def _formatear_lista_con_comillas_y(elementos: list[str]) -> str:
    elementos = [str(e).strip() for e in elementos if str(e).strip()]
    if not elementos:
        return ""
    entrecomilladas = [f"“{e}”" for e in elementos]
    if len(entrecomilladas) == 1:
        return entrecomilladas[0]
    return ", ".join(entrecomilladas[:-1]) + " y " + entrecomilladas[-1]


def _normalizar_espacios(texto) -> str:
    """Colapsa cualquier corrida de espacios en blanco (incluye saltos de
    linea y tabs, que a veces trae el objeto del proceso crudo del
    scraping) a un solo espacio y recorta los extremos."""
    return re.sub(r"\s+", " ", str(texto or "")).strip()


PREFIJO_NEGRITA_OBSERVACION = "NO APLICA"


def _observacion_partes(objeto_proceso, llenar: bool) -> tuple[str, str]:
    """Columna 'Observaciones', partida en (parte_negrita, parte_normal)
    para poder insertarla como dos runs con distinto `bold` (ver
    _agregar_tabla_procesos): solo la palabra "NO APLICA" va en negrita,
    el resto del texto fijo + el objeto del proceso va en texto normal.

    Si `llenar` es False (checkbox "Llenar Observaciones con 'NO APLICA'"
    destildado en la UI), devuelve ("", "") -- celda vacia. Si es True,
    TODAS las filas reciben `OBSERVACION_TEXTO` seguido del objeto del
    proceso COMPLETO (sin recortar), en mayusculas y sin espacios dobles
    ni saltos de linea.

    Si `OBSERVACION_TEXTO` (configurable via .env) no empieza con
    "NO APLICA" -- por ejemplo si se cambio la redaccion -- no hay nada
    que poner en negrita y todo el texto va en la parte normal."""
    if not llenar:
        return "", ""
    texto_completo = f"{OBSERVACION_TEXTO}{_normalizar_espacios(objeto_proceso).upper()}"
    if OBSERVACION_TEXTO.startswith(PREFIJO_NEGRITA_OBSERVACION):
        return PREFIJO_NEGRITA_OBSERVACION, texto_completo[len(PREFIJO_NEGRITA_OBSERVACION):]
    return "", texto_completo


def _agregar_bloque_rango(documento: Document, rango_texto: str, palabra_clave: str) -> None:
    parrafo_rango = documento.add_paragraph()
    parrafo_rango.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_etiqueta = parrafo_rango.add_run("RANGO DE BUSQUEDA:")
    _aplicar_fuente(run_etiqueta, TAMANO_CUERPO_PT, negrita=True)
    run_valor = parrafo_rango.add_run(f" {rango_texto}")
    _aplicar_fuente(run_valor, TAMANO_CUERPO_PT, negrita=False)

    parrafo_palabra = documento.add_paragraph()
    parrafo_palabra.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_etiqueta_palabra = parrafo_palabra.add_run("PALABRA CLAVE")
    _aplicar_fuente(run_etiqueta_palabra, TAMANO_CUERPO_PT, negrita=True)
    run_valor_palabra = parrafo_palabra.add_run(f": {palabra_clave.upper()}")
    _aplicar_fuente(run_valor_palabra, TAMANO_CUERPO_PT, negrita=False)


def _agregar_hipervinculo(parrafo, texto: str, url: str, tamano_pt: float = TAMANO_TABLA_PT) -> None:
    """python-docx no expone hyperlinks reales de forma nativa: se arma a
    mano el elemento OOXML <w:hyperlink>."""
    parte = parrafo.part
    id_relacion = parte.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), id_relacion)

    run = OxmlElement("w:r")
    propiedades = OxmlElement("w:rPr")

    fuentes = OxmlElement("w:rFonts")
    fuentes.set(qn("w:ascii"), FUENTE)
    fuentes.set(qn("w:hAnsi"), FUENTE)
    fuentes.set(qn("w:eastAsia"), FUENTE)
    propiedades.append(fuentes)

    tamano = OxmlElement("w:sz")
    tamano.set(qn("w:val"), str(int(tamano_pt * 2)))  # w:sz esta en medios-puntos
    propiedades.append(tamano)

    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    propiedades.append(color)
    subrayado = OxmlElement("w:u")
    subrayado.set(qn("w:val"), "single")
    propiedades.append(subrayado)
    run.append(propiedades)

    texto_run = OxmlElement("w:t")
    texto_run.text = texto
    run.append(texto_run)
    hyperlink.append(run)
    parrafo._p.append(hyperlink)


def _anchos_columnas_tabla() -> list[Cm]:
    return [Cm(valor_cm) for valor_cm in ANCHOS_COLUMNAS_CM]


def _fijar_ancho_y_alineacion_fila(celdas, anchos: list[Length]) -> None:
    for celda, ancho in zip(celdas, anchos, strict=False):
        celda.width = ancho
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _agregar_tabla_procesos(documento: Document, filas: pd.DataFrame, llenar_observaciones: bool) -> None:
    tabla = documento.add_table(rows=1, cols=len(COLUMNAS_TABLA_REPORTE))
    tabla.style = "Table Grid"
    tabla.autofit = False  # respeta los anchos fijos en vez de autoajustar al contenido
    _configurar_propiedades_tabla(tabla)

    anchos = _anchos_columnas_tabla()
    for columna, ancho in zip(tabla.columns, anchos, strict=False):
        columna.width = ancho
    _fijar_ancho_y_alineacion_fila(tabla.rows[0].cells, anchos)
    _configurar_propiedades_fila(tabla.rows[0], es_encabezado=True)

    for indice_col, (celda, nombre) in enumerate(zip(tabla.rows[0].cells, COLUMNAS_TABLA_REPORTE, strict=False)):
        celda.text = nombre
        tamano = TAMANO_OBSERVACIONES_PT if indice_col == INDICE_COLUMNA_OBSERVACIONES else TAMANO_TABLA_PT
        for parrafo in celda.paragraphs:
            for run in parrafo.runs:
                _aplicar_fuente(run, tamano, negrita=True)

    for numero, (_, fila) in enumerate(filas.iterrows(), start=1):
        fila_tabla = tabla.add_row()
        celdas = fila_tabla.cells
        _fijar_ancho_y_alineacion_fila(celdas, anchos)
        _configurar_propiedades_fila(fila_tabla)

        celdas[0].text = str(numero)
        celdas[2].text = str(fila.get("entidad_contratante") or "")
        celdas[3].text = str(fila.get("objeto_proceso") or "")
        celdas[4].text = str(fila.get("estado") or "")
        celdas[5].text = str(fila.get("provincia_canton") or "")
        celdas[6].text = _formatear_moneda(fila.get("presupuesto_referencial"))
        celdas[7].text = _formatear_fecha_corta(fila.get("fecha_publicacion"))

        # Observaciones: dos runs en el mismo parrafo, en vez de
        # `celda.text = ...`, para que solo "NO APLICA" quede en negrita
        # y el resto (texto fijo + objeto del proceso) en texto normal.
        parte_negrita, parte_normal = _observacion_partes(fila.get("objeto_proceso"), llenar_observaciones)
        parrafo_observacion = celdas[INDICE_COLUMNA_OBSERVACIONES].paragraphs[0]
        if parte_negrita:
            run_negrita = parrafo_observacion.add_run(parte_negrita)
            _aplicar_fuente(run_negrita, TAMANO_OBSERVACIONES_PT, negrita=True)
        if parte_normal:
            run_normal = parrafo_observacion.add_run(parte_normal)
            _aplicar_fuente(run_normal, TAMANO_OBSERVACIONES_PT, negrita=False)

        for indice_celda in (0, 2, 3, 4, 5, 6, 7):
            for parrafo in celdas[indice_celda].paragraphs:
                for run in parrafo.runs:
                    _aplicar_fuente(run, TAMANO_TABLA_PT)

        codigo_texto = str(fila.get("codigo") or "")
        url = fila.get("url")
        parrafo_codigo = celdas[1].paragraphs[0]
        if url and str(url).strip():
            _agregar_hipervinculo(parrafo_codigo, codigo_texto, str(url).strip(), tamano_pt=TAMANO_TABLA_PT)
        else:
            run_codigo = parrafo_codigo.add_run(codigo_texto)
            _aplicar_fuente(run_codigo, TAMANO_TABLA_PT)


def generar_reporte(
    df: pd.DataFrame,
    palabras_clave: list[str],
    fecha_inicio_global,
    fecha_fin_global,
    ruta_salida: str | Path = "reporte_contrataciones.docx",
    capturas_dir: str | Path = "capturas",
    directorio_salidas_capturas: str | Path | None = None,
    llenar_observaciones: bool = True,
) -> Path:
    """Genera el informe .docx completo y lo guarda en `ruta_salida`.

    - `df`: dataset con (al menos) las columnas id, entidad_contratante,
      objeto_proceso, estado, provincia_canton, presupuesto_referencial,
      fecha_publicacion, palabra_clave, codigo, url.
    - `palabras_clave`: lista de palabras clave a documentar, en el orden
      en que deben aparecer en el informe.
    - `fecha_inicio_global` / `fecha_fin_global`: rango global (str ISO o
      date/datetime) usado en el parrafo introductorio.
    - `directorio_salidas_capturas`: donde se guardan las partes de una
      captura demasiado alta para una pagina (ver
      scripts/reportes_capturas.py::dividir_imagen_si_no_cabe). Por
      defecto, DIRECTORIO_SALIDAS_CAPTURAS (salidas/capturas/); los tests
      lo sobreescriben con un directorio temporal.
    - `llenar_observaciones`: si es True (default), la columna
      "Observaciones" de la tabla lleva `OBSERVACION_TEXTO` + el objeto
      del proceso completo en TODAS las filas (ver _observacion_partes).
      Si es False, la columna queda vacia -- checkbox "Llenar
      Observaciones con 'NO APLICA'" en la UI.
    """
    documento = Document()
    capturas_path = Path(capturas_dir)
    directorio_salidas_capturas = Path(directorio_salidas_capturas or DIRECTORIO_SALIDAS_CAPTURAS)

    estilo_normal = documento.styles["Normal"]
    estilo_normal.font.name = FUENTE
    estilo_normal.font.size = Pt(TAMANO_CUERPO_PT)

    # Alto util de la pagina (alto de pagina menos margenes superior e
    # inferior), en EMU -- la misma unidad que usan Inches/Cm/Length de
    # python-docx. Cualquier captura que, insertada a Inches(6) de ancho,
    # renderice mas alto que esto se divide en partes (ver _agregar_captura).
    seccion = documento.sections[0]
    alto_util_pagina = seccion.page_height - seccion.top_margin - seccion.bottom_margin

    lista_comillas = _formatear_lista_con_comillas_y(palabras_clave)
    anios = _anios_entre(fecha_inicio_global, fecha_fin_global)

    parrafo_intro = documento.add_paragraph()
    parrafo_intro.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def _run_intro(texto: str, negrita: bool = False):
        run = parrafo_intro.add_run(texto)
        _aplicar_fuente(run, TAMANO_CUERPO_PT, negrita=negrita)
        return run

    _run_intro("1.- ", negrita=True)
    _run_intro("Se procede a realizar la búsqueda en el ")
    _run_intro("PORTAL DE COMPRAS PÚBLICAS", negrita=True)
    _run_intro(", con la primera palabra clave ")
    _run_intro(lista_comillas, negrita=True)
    _run_intro(
        f" en un periodo dentro de los {anios} ({_numero_en_letras(anios)}) años, "
        f"desde el {_formatear_fecha_larga(fecha_inicio_global, 'del')} hasta el "
        f"{_formatear_fecha_larga(fecha_fin_global, 'del')}, estas búsquedas pueden "
        "verificarse en la presente documentación, se detallan observaciones del "
        "análisis realizado y los respaldos gráficos (capturas de pantalla) de las "
        "contrataciones anteriores realizadas a nivel nacional."
    )

    clave_normalizada_por_fila = df["palabra_clave"].map(_normalizar_texto)
    rango_fechas_global = (
        f"{_formatear_fecha_larga_mayusculas(fecha_inicio_global)} A "
        f"{_formatear_fecha_larga_mayusculas(fecha_fin_global)}"
    )

    # Numera las capturas ("Captura N") de forma continua a lo largo de
    # TODO el documento (no por palabra clave), para que no se repita un
    # mismo numero en secciones distintas del reporte.
    contador_capturas = 0

    for palabra_clave in palabras_clave:
        df_palabra = df[clave_normalizada_por_fila == _normalizar_texto(palabra_clave)]
        if df_palabra.empty:
            continue
        if "id" in df_palabra.columns:
            df_palabra = df_palabra.sort_values("id")

        parrafo_proceso = documento.add_paragraph()
        parrafo_proceso.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_proceso = parrafo_proceso.add_run("Proceso Régimen Común")
        _aplicar_fuente(run_proceso, TAMANO_TITULO_PT, negrita=True)

        parrafo_palabra_titulo = documento.add_paragraph()
        parrafo_palabra_titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_etiqueta_titulo = parrafo_palabra_titulo.add_run("Palabra Clave: ")
        _aplicar_fuente(run_etiqueta_titulo, TAMANO_TITULO_PT, negrita=True)
        run_palabra_roja = parrafo_palabra_titulo.add_run(palabra_clave.upper())
        _aplicar_fuente(run_palabra_roja, TAMANO_TITULO_PT, negrita=True)
        run_palabra_roja.font.color.rgb = COLOR_PALABRA_CLAVE_TITULO

        _agregar_bloque_rango(documento, rango_fechas_global, palabra_clave)

        lotes = lotes_de_capturas(capturas_path, palabra_clave)
        semestres = rangos_semestrales(fecha_inicio_global, fecha_fin_global)
        imagenes_por_semestre = asignar_lotes_a_semestres(df_palabra, lotes, semestres)
        for indice, (inicio_semestre, fin_semestre) in enumerate(semestres):
            rango_semestre = (
                f"{_formatear_fecha_larga_mayusculas(inicio_semestre)} A "
                f"{_formatear_fecha_larga_mayusculas(fin_semestre)}"
            )
            _agregar_bloque_rango(documento, rango_semestre, palabra_clave)

            for imagen in imagenes_por_semestre[indice]:
                contador_capturas += 1
                _agregar_captura(
                    documento, imagen, Inches(6), alto_util_pagina, contador_capturas, directorio_salidas_capturas
                )

        parrafo_existen = documento.add_paragraph()
        parrafo_existen.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run_existen = parrafo_existen.add_run(
            f"EXISTEN {len(df_palabra)} PROCESOS LOS MISMOS QUE SERÁN "
            "ANALIZADOS. En este cuadro se visualiza los links "
            "correspondientes a través de los cuales se puede acceder a la "
            "información correspondiente del proceso para su análisis."
        )
        _aplicar_fuente(run_existen, TAMANO_CUERPO_PT)

        _agregar_tabla_procesos(documento, df_palabra, llenar_observaciones)

    ruta_salida = Path(ruta_salida)
    documento.save(str(ruta_salida))
    return ruta_salida
