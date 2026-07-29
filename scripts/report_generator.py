"""Ensambla un informe .docx (Word) que documenta las busquedas realizadas
en el portal de Compras Publicas (SERCOP) via `scripts/scrape_portal.py`.

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
   (semestre) dentro de ese rango global (ver `_rangos_semestrales`),
   seguido de las capturas de pantalla que le correspondan a ese
   semestre por la fecha real de sus datos (ver `_lotes_de_capturas` /
   `_asignar_lotes_a_semestres`), con borde negro solido. Si una misma
   palabra clave se busco varias veces dentro del mismo semestre, todos
   esos lotes de capturas se agrupan bajo ese semestre (no se pierde
   ninguno).
4. La declaracion "EXISTEN [N] PROCESOS LOS MISMOS QUE SERÁN ANALIZADOS."
5. Una unica tabla (fuente Tahoma, columnas de ancho fijo) con todos los
   procesos de esa palabra clave.

El parrafo introductorio ("1.- Se procede...") va en Tahoma 10,
justificado, con negrita selectiva en "1.- ", "PORTAL DE COMPRAS
PÚBLICAS" y la lista de palabras clave entrecomilladas (“asi”), igual
que el modelo de referencia; el resto del texto general (incluida la
linea "EXISTEN...") no lleva negrita.

Uso tipico (df ya cargado con las columnas del esquema de la API/BD:
id, codigo, entidad_contratante, objeto_proceso, estado,
provincia_canton, presupuesto_referencial, fecha_publicacion,
palabra_clave, url):

    from scripts.report_generator import generar_reporte

    generar_reporte(
        df=df,
        palabras_clave=["luminarias", "repotenciacion"],
        fecha_inicio_global="2025-07-01",
        fecha_fin_global="2026-06-30",
    )
"""
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

# Estilo del documento: tipografia general del cuerpo, de titulos y de
# la tabla, mas el borde de las capturas de pantalla.
FUENTE = "Tahoma"
TAMANO_CUERPO_PT = 10
TAMANO_TITULO_PT = 12
TAMANO_TABLA_PT = 6  # 5 o 6 pt son legibles en celdas compactas; 6 por legibilidad
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

# Cada palabra clave se documenta ademas en bloques de 6 meses (semestres)
# dentro del rango global, empezando en fecha_inicio_global -- asi es como
# el portal SERCOP limita cada busqueda individual (hasta 6 meses antes y
# 15 dias despues de la fecha de publicacion). Ver `_rangos_semestrales`.
MESES_POR_SEMESTRE = 6

# Propiedades de tabla pedidas explicitamente (vistas en el dialogo
# "Propiedades de tabla" de Word): sangria negativa (extiende la tabla
# mas alla del margen izquierdo normal) y alto minimo de fila. Ver
# `_configurar_propiedades_tabla`/`_configurar_propiedades_fila`.
INDENTACION_TABLA_CM = -2.51
ALTO_MINIMO_FILA_CM = 0.04

# Ancho FIJO de cada columna de la tabla, en cm (mismo orden que
# COLUMNAS_TABLA_REPORTE) -- medida exacta, no proporcional. El ancho
# preferido de la tabla (tblW) es la suma de estos valores, para que
# quede consistente con el ancho real de las columnas.
ANCHOS_COLUMNAS_CM = [1, 2, 3, 4.06, 2, 2, 2, 2, 3]
ANCHO_TABLA_CM = sum(ANCHOS_COLUMNAS_CM)

PATRON_CAPTURA_NUEVO = re.compile(
    r"^(?P<slug>.+)_(?P<lote_slug>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})_pag_(?P<pagina>\d+)\.png$"
)
PATRON_CAPTURA_LEGADO = re.compile(
    r"^(?P<slug>.+)_(?P<dia>\d{2})-(?P<mes>[a-zA-Z]+)-(?P<anio>\d{4})_pag_(?P<pagina>\d+)\.png$"
)

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

TEXTO_NO_APLICA = (
    "NO APLICA, ESTE PROCESO NO SE CONSIDERA POR SER DE CARACTERISTICAS "
    "DIFERENTE A LO QUE SE REQUIERE OBJETO DE CONTRATACIÓN DIFERENTE - "
)


def _normalizar_texto(texto) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto or ""))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


def _aplicar_fuente(run, tamano_pt: float, negrita: bool | None = None, fuente: str = FUENTE) -> None:
    """Fija fuente/tamano/negrita de un run. Ademas de `run.font.name`
    (que Word solo respeta para texto "ascii"/latino), setea tambien
    `w:eastAsia` en las propiedades del run: es un gotcha conocido de
    python-docx/Word donde, sin ese atributo, algunos renderizadores
    ignoran la fuente elegida."""
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


def _agregar_borde_imagen(
    forma, color_hex: str = COLOR_BORDE_IMAGEN, grosor_pt: float = GROSOR_BORDE_IMAGEN_PT
) -> None:
    """Agrega un borde solido visible a una imagen insertada con
    `document.add_picture` (python-docx no expone esto de forma nativa):
    se arma a mano el elemento <a:ln> dentro de las propiedades de forma
    de la imagen (<pic:spPr>)."""
    propiedades_forma = forma._inline.graphic.graphicData.pic.spPr
    linea = OxmlElement("a:ln")
    linea.set("w", str(int(grosor_pt * 12700)))  # EMUs: 1pt = 12700 EMU
    relleno = OxmlElement("a:solidFill")
    color = OxmlElement("a:srgbClr")
    color.set("val", color_hex)
    relleno.append(color)
    linea.append(relleno)
    propiedades_forma.append(linea)


def _configurar_propiedades_tabla(tabla) -> None:
    """Ancho preferido fijo, alineacion izquierda con sangria negativa y
    "sin ajuste de texto" (una tabla normal/no flotante, sin <w:tblpPr>,
    ya se comporta asi por defecto). python-docx no expone `tblW`/
    `tblInd` via su API publica, asi que se arman a mano en <w:tblPr>."""
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
    """Alto minimo de fila, "permitir dividir entre paginas" y, solo para
    la fila de encabezado, "repetir como fila de encabezado en cada
    pagina". El orden de insercion en <w:trPr> importa para el esquema
    OOXML (cantSplit, trHeight, tblHeader, en ese orden), por eso
    `cantSplit` se agrega ANTES de fijar `height`/`height_rule` (que crea
    <w:trHeight>) y `tblHeader` se agrega despues."""
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


def _slug_palabra_clave(palabra_clave: str) -> str:
    """Debe coincidir EXACTAMENTE con la logica de
    `scripts/scrape_portal.py::_slug_palabra_clave` (asi es como se nombran
    los archivos en capturas/): minusculas, sin acentos, solo alfanumericos
    separados por guion bajo."""
    sin_acentos = unicodedata.normalize("NFKD", str(palabra_clave or ""))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")
    return slug or "sin_palabra_clave"


def _formatear_fecha_larga(valor, conector_anio: str = "de") -> str:
    """'2026-07-23' -> '23 de julio de 2026' (conector_anio='de', para
    los encabezados de RANGO DE BUSQUEDA en mayusculas) o '23 de julio
    del 2026' (conector_anio='del', para el parrafo introductorio, que
    asi lo redacta el modelo de referencia)."""
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return str(valor)
    meses_por_numero = {v: k for k, v in MESES_ES.items()}
    return f"{fecha.day} de {meses_por_numero[fecha.month]} {conector_anio} {fecha.year}"


def _formatear_fecha_larga_mayusculas(valor) -> str:
    """'2026-07-23' -> '23 DE JULIO DE 2026' (para los encabezados de
    RANGO DE BUSQUEDA)."""
    return _formatear_fecha_larga(valor, conector_anio="de").upper()


def _numero_en_letras(numero: int) -> str:
    return NUMEROS_EN_LETRAS.get(numero, str(numero))


def _anios_entre(fecha_inicio, fecha_fin) -> int:
    """Cantidad de años (redondeada, minimo 1) entre dos fechas, para la
    frase 'dentro de los N (n_en_letras) años' del parrafo introductorio."""
    inicio = pd.to_datetime(fecha_inicio, errors="coerce")
    fin = pd.to_datetime(fecha_fin, errors="coerce")
    if pd.isna(inicio) or pd.isna(fin):
        return 1
    dias = (fin - inicio).days
    return max(1, round(dias / 365.25))


def _formatear_fecha_corta(valor) -> str:
    """'2026-07-23...' -> '23/07/2026'; vacio/no parseable -> '' o el valor tal cual."""
    if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return str(valor)
    return fecha.strftime("%d/%m/%Y")


def _formatear_moneda(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    try:
        return f"$ {float(valor):,.2f}"
    except (TypeError, ValueError):
        return str(valor)


def _formatear_lista_con_comillas_y(elementos: list[str]) -> str:
    """['a'] -> '“a”'; ['a','b'] -> '“a” y “b”'; ['a','b','c'] ->
    '“a”, “b” y “c”' (comillas tipograficas, como en el parrafo
    introductorio del modelo de referencia)."""
    elementos = [str(e).strip() for e in elementos if str(e).strip()]
    if not elementos:
        return ""
    entrecomilladas = [f"“{e}”" for e in elementos]
    if len(entrecomilladas) == 1:
        return entrecomilladas[0]
    return ", ".join(entrecomilladas[:-1]) + " y " + entrecomilladas[-1]


def _primeras_palabras(texto, n: int = 8) -> str:
    return " ".join(str(texto or "").split()[:n])


def _observacion(objeto_proceso, palabra_clave: str) -> str:
    """Celda 'Observaciones': vacia si el objeto del proceso menciona la
    palabra clave buscada; si no, el texto fijo pedido + las primeras
    palabras del objeto real, para poder identificar el proceso a simple
    vista sin tener que abrir el link."""
    if _normalizar_texto(palabra_clave) in _normalizar_texto(objeto_proceso):
        return ""
    return TEXTO_NO_APLICA + _primeras_palabras(objeto_proceso)


def _slug_lote_id(lote_id) -> str | None:
    """Debe coincidir EXACTAMENTE con la logica de
    `scripts/scrape_portal.py::_slug_lote_id` (asi es como se nombran las
    capturas del formato nuevo): reemplaza los caracteres invalidos en un
    nombre de archivo (los ":" del timestamp ISO) por "-". Devuelve None
    para valores vacios/nulos."""
    if lote_id is None or (isinstance(lote_id, float) and pd.isna(lote_id)):
        return None
    texto = str(lote_id).strip()
    if not texto:
        return None
    return re.sub(r"[^A-Za-z0-9_-]", "-", texto)


def _lotes_de_capturas(capturas_dir: Path, palabra_clave: str) -> list[tuple[str, list[Path]]]:
    """Agrupa las capturas de pantalla de `capturas_dir` que pertenecen a
    `palabra_clave` por ejecucion de scraping (un grupo = las paginas de
    una misma busqueda), en orden cronologico. Devuelve pares
    (clave_de_orden, imagenes); `_asignar_lotes_a_semestres` usa esa
    clave para emparejar cada lote con el bloque semestral que le
    corresponda por FECHA REAL, no por posicion.

    Reconoce los dos formatos de nombre de archivo que usa
    `scripts/scrape_portal.py`:
    - Nuevo: `[slug]_[lote_id]_pag_[N].png` (lote_id slugificado, unico
      por ejecucion, con precision de segundos).
    - Legado (capturas de antes de esa migracion): `[slug]_[fecha]_pag_[N].png`
      (solo la fecha del dia)."""
    slug = _slug_palabra_clave(palabra_clave)
    if not capturas_dir.exists():
        return []

    imagenes_por_clave: dict = {}
    orden_por_clave: dict = {}

    for archivo in capturas_dir.iterdir():
        coincidencia = PATRON_CAPTURA_NUEVO.match(archivo.name)
        if coincidencia and coincidencia.group("slug") == slug:
            clave = coincidencia.group("lote_slug")
            orden_por_clave[clave] = clave
            imagenes_por_clave.setdefault(clave, []).append(
                (int(coincidencia.group("pagina")), archivo)
            )
            continue

        coincidencia = PATRON_CAPTURA_LEGADO.match(archivo.name)
        if coincidencia and coincidencia.group("slug") == slug:
            mes_num = MESES_ES.get(coincidencia.group("mes").lower())
            if mes_num is None:
                continue
            fecha = pd.Timestamp(
                year=int(coincidencia.group("anio")), month=mes_num, day=int(coincidencia.group("dia"))
            ).date()
            clave = f"{fecha.isoformat()}T00-00-00"
            orden_por_clave[clave] = clave
            imagenes_por_clave.setdefault(clave, []).append(
                (int(coincidencia.group("pagina")), archivo)
            )

    lotes = []
    for clave in sorted(imagenes_por_clave, key=lambda c: orden_por_clave[c]):
        paginas_ordenadas = sorted(imagenes_por_clave[clave], key=lambda t: t[0])
        lotes.append((clave, [ruta for _, ruta in paginas_ordenadas]))
    return lotes


def _asignar_lotes_a_semestres(
    df_palabra: pd.DataFrame,
    lotes: list[tuple[str, list[Path]]],
    semestres: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> list[list[Path]]:
    """Asigna cada lote de capturas al semestre que le corresponde por
    FECHA REAL (no por posicion, para no perder lotes cuando hay mas
    ejecuciones de scraping que semestres calculados -- p.ej. la misma
    palabra clave buscada varias veces dentro del mismo semestre).

    Para lotes del formato nuevo, la fecha ancla es la mediana de
    `fecha_publicacion` de las filas de `df_palabra` con ese `lote_id`
    (join por `lote_id` slugificado). Si no hay filas con ese lote_id
    (formato legado, o el lote no dejo filas en esta palabra clave), se
    usa la fecha embebida en la propia clave de orden del lote como
    respaldo. El lote se coloca en el semestre cuyo rango contiene esa
    fecha ancla (o el ultimo semestre si la fecha cae despues de todos)."""
    resultado: list[list[Path]] = [[] for _ in semestres]
    if not semestres:
        return resultado

    lote_slug_por_fila = (
        df_palabra["lote_id"].map(_slug_lote_id)
        if "lote_id" in df_palabra.columns
        else pd.Series(dtype=object)
    )

    for clave_orden, imagenes in lotes:
        ancla = None
        if not lote_slug_por_fila.empty:
            filas_lote = df_palabra[lote_slug_por_fila == clave_orden]
            fechas_lote = pd.to_datetime(filas_lote.get("fecha_publicacion"), errors="coerce").dropna()
            if not fechas_lote.empty:
                ancla = fechas_lote.median()
        if ancla is None:
            ancla = pd.to_datetime(clave_orden.split("T")[0], errors="coerce")

        indice = len(semestres) - 1
        if not pd.isna(ancla):
            for i, (inicio, fin) in enumerate(semestres):
                if inicio <= ancla <= fin:
                    indice = i
                    break
        resultado[indice].extend(imagenes)

    return resultado


def _rangos_semestrales(fecha_inicio_global, fecha_fin_global) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Divide [fecha_inicio_global, fecha_fin_global] en bloques
    consecutivos de `MESES_POR_SEMESTRE` (6) meses calendario, empezando
    en fecha_inicio_global. El ultimo bloque se recorta a
    fecha_fin_global si el bloque calculado se pasa de esa fecha. Si el
    rango es invalido o de un solo dia, devuelve un unico bloque con todo
    el rango en vez de una lista vacia."""
    inicio = pd.to_datetime(fecha_inicio_global)
    fin = pd.to_datetime(fecha_fin_global)
    if pd.isna(inicio) or pd.isna(fin) or inicio >= fin:
        return [(inicio, fin)]

    bloques = []
    cursor = inicio
    while cursor < fin:
        fin_bloque = cursor + pd.DateOffset(months=MESES_POR_SEMESTRE)
        if fin_bloque > fin:
            fin_bloque = fin
        bloques.append((cursor, fin_bloque))
        cursor = fin_bloque
    return bloques


def _agregar_bloque_rango(documento: Document, rango_texto: str, palabra_clave: str) -> None:
    """Par de lineas "RANGO DE BUSQUEDA: .../PALABRA CLAVE: ...", Tahoma
    10 (tamaño de cuerpo), alineadas a la izquierda, con negrita SOLO en
    la etiqueta ("RANGO DE BUSQUEDA:" / "PALABRA CLAVE"), no en el valor.
    Se usa tanto para el rango global como para cada bloque semestral."""
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
    mano el elemento OOXML <w:hyperlink> con su relacion externa (receta
    estandar de la comunidad de python-docx). El run se arma directo en
    XML (no via `Run`/`_aplicar_fuente`), asi que la fuente/tamano se
    fijan aqui con los mismos elementos <w:rFonts>/<w:sz>."""
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
    """Ancho fijo de cada columna, tal como se pide explicitamente (en
    cm) en `ANCHOS_COLUMNAS_CM`: medida exacta por columna, no una
    proporcion calculada."""
    return [Cm(valor_cm) for valor_cm in ANCHOS_COLUMNAS_CM]


def _fijar_ancho_y_alineacion_fila(celdas, anchos: list[Length]) -> None:
    for celda, ancho in zip(celdas, anchos):
        # python-docx solo respeta `table.columns[i].width` de forma
        # confiable si TAMBIEN se fija el ancho de cada celda individual
        # de esa columna (gotcha conocido de la libreria/Word).
        celda.width = ancho
        celda.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _agregar_tabla_procesos(documento: Document, filas: pd.DataFrame, palabra_clave: str) -> None:
    tabla = documento.add_table(rows=1, cols=len(COLUMNAS_TABLA_REPORTE))
    tabla.style = "Table Grid"
    tabla.autofit = False  # respeta los anchos fijos en vez de autoajustar al contenido
    _configurar_propiedades_tabla(tabla)

    anchos = _anchos_columnas_tabla()
    for columna, ancho in zip(tabla.columns, anchos):
        columna.width = ancho
    _fijar_ancho_y_alineacion_fila(tabla.rows[0].cells, anchos)
    _configurar_propiedades_fila(tabla.rows[0], es_encabezado=True)

    for celda, nombre in zip(tabla.rows[0].cells, COLUMNAS_TABLA_REPORTE):
        celda.text = nombre
        for parrafo in celda.paragraphs:
            for run in parrafo.runs:
                _aplicar_fuente(run, TAMANO_TABLA_PT, negrita=True)

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
        celdas[8].text = _observacion(fila.get("objeto_proceso"), palabra_clave)

        for indice_celda in (0, 2, 3, 4, 5, 6, 7, 8):
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
) -> Path:
    """Genera el informe .docx completo y lo guarda en `ruta_salida`.

    - `df`: dataset con (al menos) las columnas id, entidad_contratante,
      objeto_proceso, estado, provincia_canton, presupuesto_referencial,
      fecha_publicacion, palabra_clave, codigo, url.
    - `palabras_clave`: lista de palabras clave a documentar, en el orden
      en que deben aparecer en el informe.
    - `fecha_inicio_global` / `fecha_fin_global`: rango global (str ISO o
      date/datetime) usado en el parrafo introductorio.
    """
    documento = Document()
    capturas_path = Path(capturas_dir)

    # Tahoma 10 como fuente base del documento (estilo "Normal"): cualquier
    # texto que no reciba un run/tamano explicito hereda esto igual.
    estilo_normal = documento.styles["Normal"]
    estilo_normal.font.name = FUENTE
    estilo_normal.font.size = Pt(TAMANO_CUERPO_PT)

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

    for palabra_clave in palabras_clave:
        df_palabra = df[clave_normalizada_por_fila == _normalizar_texto(palabra_clave)]
        if df_palabra.empty:
            continue
        if "id" in df_palabra.columns:
            df_palabra = df_palabra.sort_values("id")

        # Bloque de titulo (una vez por palabra clave): "Proceso Régimen
        # Común" + "Palabra Clave: X" (X en rojo), centrado, sin sombreado.
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

        # Rango global (una vez por palabra clave).
        _agregar_bloque_rango(documento, rango_fechas_global, palabra_clave)

        # Bloques semestrales: cada uno con su propio par RANGO/PALABRA
        # CLAVE, seguido de las capturas que le correspondan (ver
        # `_asignar_lotes_a_semestres`: se emparejan por la fecha real de
        # los datos de cada lote, no por posicion, para no perder lotes
        # cuando hay mas ejecuciones de scraping que semestres). Si un
        # semestre no tiene ningun lote asignado, queda con el
        # encabezado pero sin capturas debajo.
        lotes = _lotes_de_capturas(capturas_path, palabra_clave)
        semestres = _rangos_semestrales(fecha_inicio_global, fecha_fin_global)
        imagenes_por_semestre = _asignar_lotes_a_semestres(df_palabra, lotes, semestres)
        for indice, (inicio_semestre, fin_semestre) in enumerate(semestres):
            rango_semestre = (
                f"{_formatear_fecha_larga_mayusculas(inicio_semestre)} A "
                f"{_formatear_fecha_larga_mayusculas(fin_semestre)}"
            )
            _agregar_bloque_rango(documento, rango_semestre, palabra_clave)

            for imagen in imagenes_por_semestre[indice]:
                forma = documento.add_picture(str(imagen), width=Inches(6))
                _agregar_borde_imagen(forma)

        parrafo_existen = documento.add_paragraph()
        parrafo_existen.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run_existen = parrafo_existen.add_run(
            f"EXISTEN {len(df_palabra)} PROCESOS LOS MISMOS QUE SERÁN "
            "ANALIZADOS. En este cuadro se visualiza los links "
            "correspondientes a través de los cuales se puede acceder a la "
            "información correspondiente del proceso para su análisis."
        )
        _aplicar_fuente(run_existen, TAMANO_CUERPO_PT)

        _agregar_tabla_procesos(documento, df_palabra, palabra_clave)

    ruta_salida = Path(ruta_salida)
    documento.save(str(ruta_salida))
    return ruta_salida


if __name__ == "__main__":
    # Demo/smoke test: arma un reporte con todo lo que haya en la base de
    # datos local, agrupado por cada palabra_clave distinta encontrada.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import database  # noqa: E402

    registros = database.get_all_contrataciones()
    df_demo = pd.DataFrame(registros)
    if df_demo.empty:
        print("No hay datos en la base local; no se genero ningun reporte.")
    else:
        claves = sorted(df_demo["palabra_clave"].dropna().unique().tolist())
        fechas = pd.to_datetime(df_demo["fecha_publicacion"], errors="coerce").dropna()
        ruta = generar_reporte(
            df=df_demo,
            palabras_clave=claves,
            fecha_inicio_global=fechas.min(),
            fecha_fin_global=fechas.max(),
        )
        print(f"Reporte generado en: {ruta.resolve()}")
