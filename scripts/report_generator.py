"""Ensambla un informe .docx (Word) que documenta las busquedas realizadas
en el portal de Compras Publicas (SERCOP) via `scripts/scrape_portal.py`.

Por cada palabra clave, el informe agrega:
1. Un encabezado consolidado en una sola linea: "RANGO DE BUSQUEDA:
   [fecha_inicio_global] A [fecha_fin_global] / PALABRA CLAVE:
   [PALABRA CLAVE EN MAYUSCULAS]" (el rango es el global de toda la
   busqueda, no uno distinto por cada ejecucion de scraping).
2. Todas las capturas de pantalla de esa palabra clave encontradas en
   `capturas/` (ver `_imagenes_de_capturas`), como respaldo visual.
3. La declaracion "EXISTEN [N] PROCESOS LOS MISMOS QUE SERÁN ANALIZADOS."
4. Una unica tabla con todos los procesos de esa palabra clave.

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
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

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


def _slug_palabra_clave(palabra_clave: str) -> str:
    """Debe coincidir EXACTAMENTE con la logica de
    `scripts/scrape_portal.py::_slug_palabra_clave` (asi es como se nombran
    los archivos en capturas/): minusculas, sin acentos, solo alfanumericos
    separados por guion bajo."""
    sin_acentos = unicodedata.normalize("NFKD", str(palabra_clave or ""))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")
    return slug or "sin_palabra_clave"


def _formatear_fecha_larga(valor) -> str:
    """'2026-07-23' -> '23 de julio de 2026' (para el parrafo introductorio)."""
    fecha = pd.to_datetime(valor, errors="coerce")
    if pd.isna(fecha):
        return str(valor)
    meses_por_numero = {v: k for k, v in MESES_ES.items()}
    return f"{fecha.day} de {meses_por_numero[fecha.month]} de {fecha.year}"


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


def _formatear_lista_con_y(elementos: list[str]) -> str:
    """['a'] -> 'a'; ['a','b'] -> 'a y b'; ['a','b','c'] -> 'a, b y c'."""
    elementos = [str(e).strip() for e in elementos if str(e).strip()]
    if not elementos:
        return ""
    if len(elementos) == 1:
        return elementos[0]
    return ", ".join(elementos[:-1]) + " y " + elementos[-1]


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


def _imagenes_de_capturas(capturas_dir: Path, palabra_clave: str) -> list[Path]:
    """Devuelve todas las capturas de pantalla de `capturas_dir` que
    pertenecen a `palabra_clave`, ordenadas cronologicamente (y por numero
    de pagina dentro de cada ejecucion). Reconoce los dos formatos de
    nombre de archivo que usa `scripts/scrape_portal.py`:

    - Nuevo: `[slug]_[lote_id]_pag_[N].png` (lote_id slugificado, unico
      por ejecucion, con precision de segundos).
    - Legado (capturas de antes de esa migracion): `[slug]_[fecha]_pag_[N].png`
      (solo la fecha del dia)."""
    slug = _slug_palabra_clave(palabra_clave)
    if not capturas_dir.exists():
        return []

    encontradas: list[tuple[str, int, Path]] = []  # (orden, pagina, ruta)

    for archivo in capturas_dir.iterdir():
        coincidencia = PATRON_CAPTURA_NUEVO.match(archivo.name)
        if coincidencia and coincidencia.group("slug") == slug:
            orden = coincidencia.group("lote_slug")
            encontradas.append((orden, int(coincidencia.group("pagina")), archivo))
            continue

        coincidencia = PATRON_CAPTURA_LEGADO.match(archivo.name)
        if coincidencia and coincidencia.group("slug") == slug:
            mes_num = MESES_ES.get(coincidencia.group("mes").lower())
            if mes_num is None:
                continue
            fecha = pd.Timestamp(
                year=int(coincidencia.group("anio")), month=mes_num, day=int(coincidencia.group("dia"))
            ).date()
            orden = f"{fecha.isoformat()}T00-00-00"
            encontradas.append((orden, int(coincidencia.group("pagina")), archivo))

    encontradas.sort(key=lambda t: (t[0], t[1]))
    return [ruta for _, _, ruta in encontradas]


def _agregar_hipervinculo(parrafo, texto: str, url: str) -> None:
    """python-docx no expone hyperlinks reales de forma nativa: se arma a
    mano el elemento OOXML <w:hyperlink> con su relacion externa (receta
    estandar de la comunidad de python-docx)."""
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


def _agregar_tabla_procesos(documento: Document, filas: pd.DataFrame, palabra_clave: str) -> None:
    tabla = documento.add_table(rows=1, cols=len(COLUMNAS_TABLA_REPORTE))
    tabla.style = "Table Grid"

    for celda, nombre in zip(tabla.rows[0].cells, COLUMNAS_TABLA_REPORTE):
        celda.text = nombre
        for parrafo in celda.paragraphs:
            for run in parrafo.runs:
                run.bold = True

    for numero, (_, fila) in enumerate(filas.iterrows(), start=1):
        celdas = tabla.add_row().cells
        celdas[0].text = str(numero)
        celdas[2].text = str(fila.get("entidad_contratante") or "")
        celdas[3].text = str(fila.get("objeto_proceso") or "")
        celdas[4].text = str(fila.get("estado") or "")
        celdas[5].text = str(fila.get("provincia_canton") or "")
        celdas[6].text = _formatear_moneda(fila.get("presupuesto_referencial"))
        celdas[7].text = _formatear_fecha_corta(fila.get("fecha_publicacion"))
        celdas[8].text = _observacion(fila.get("objeto_proceso"), palabra_clave)

        codigo_texto = str(fila.get("codigo") or "")
        url = fila.get("url")
        parrafo_codigo = celdas[1].paragraphs[0]
        if url and str(url).strip():
            _agregar_hipervinculo(parrafo_codigo, codigo_texto, str(url).strip())
        else:
            parrafo_codigo.add_run(codigo_texto)


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

    lista_formateada = _formatear_lista_con_y(palabras_clave)
    documento.add_paragraph(
        "1.- Se procede a realizar la búsqueda en el PORTAL DE COMPRAS "
        f"PÚBLICAS, con las palabras clave {lista_formateada} en un periodo "
        f"desde el {_formatear_fecha_larga(fecha_inicio_global)} hasta el "
        f"{_formatear_fecha_larga(fecha_fin_global)}, estas búsquedas pueden "
        "verificarse en la presente documentación, se detallan observaciones "
        "del análisis realizado y los respaldos gráficos (capturas de "
        "pantalla) de las contrataciones anteriores realizadas a nivel "
        "nacional."
    )

    clave_normalizada_por_fila = df["palabra_clave"].map(_normalizar_texto)
    rango_fechas_global = (
        f"{_formatear_fecha_corta(fecha_inicio_global)} A {_formatear_fecha_corta(fecha_fin_global)}"
    )

    for palabra_clave in palabras_clave:
        df_palabra = df[clave_normalizada_por_fila == _normalizar_texto(palabra_clave)]
        if df_palabra.empty:
            continue
        if "id" in df_palabra.columns:
            df_palabra = df_palabra.sort_values("id")

        encabezado = documento.add_paragraph()
        encabezado.add_run(
            f"RANGO DE BUSQUEDA: {rango_fechas_global} / PALABRA CLAVE: {palabra_clave.upper()}"
        ).bold = True

        for imagen in _imagenes_de_capturas(capturas_path, palabra_clave):
            documento.add_picture(str(imagen), width=Inches(6))

        documento.add_paragraph(
            f"EXISTEN {len(df_palabra)} PROCESOS LOS MISMOS QUE SERÁN "
            "ANALIZADOS. En este cuadro se visualiza los links "
            "correspondientes a través de los cuales se puede acceder a la "
            "información correspondiente del proceso para su análisis."
        )
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
