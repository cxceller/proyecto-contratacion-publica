"""Sanitizador de HTML enriquecido (salida de TinyMCE) por LISTA BLANCA.

Reemplaza a la lista negra por regex que solo quitaba <script>/<style>/
<iframe>/<object>/<embed> y dejaba pasar `<img onerror=...>`, `<svg onload=...>`,
`href="javascript:..."`, etc. Usa nh3 (bindings de la libreria Rust `ammonia`,
parser HTML5 real, no regex): todo lo que no esta permitido se elimina.

Permitido:
- etiquetas de texto/tablas/listas de TinyMCE (ver TAGS_PERMITIDOS);
- atributos: href (http/https/mailto) en <a>; src/alt/width/height en <img>;
  colspan/rowspan en celdas; `style` filtrado propiedad por propiedad;
- imagenes: solo `data:image/(png|jpeg|gif|webp);base64,...` o http(s) -- el
  editor pega imagenes como data URI (paste_data_images=True);
- NUNCA: scripts, eventos on*, javascript:, data: fuera de <img>, svg, iframe,
  formularios, `url(...)`/`expression(...)` en CSS.
"""
import re

import nh3

TAGS_PERMITIDOS = {
    "a", "b", "blockquote", "br", "caption", "code", "col", "colgroup", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "s", "span", "strike", "strong", "sub",
    "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
ATRIBUTOS_PERMITIDOS = {
    "*": {"style"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "col": {"span"},
}
ESQUEMAS_URL = {"http", "https", "mailto", "data"}  # 'data' solo lo deja pasar _filtrar_atributo en <img src>

PROPIEDADES_CSS_PERMITIDAS = {
    "text-align", "font-weight", "font-style", "font-size", "text-decoration", "color", "background-color",
    "vertical-align", "width", "height", "border", "border-collapse", "padding", "margin", "line-height",
}
_VALOR_CSS_SEGURO = re.compile(r"^[#\w\s.,%()\-+/]{1,100}$")
_DATA_IMAGEN = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$")
_URL_SEGURA = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)
_NUMERO = re.compile(r"^\d{1,4}%?$")


def _filtrar_css(valor: str) -> str | None:
    permitidas = []
    for declaracion in valor.split(";"):
        if ":" not in declaracion:
            continue
        propiedad, _, contenido = declaracion.partition(":")
        propiedad, contenido = propiedad.strip().lower(), contenido.strip()
        if propiedad not in PROPIEDADES_CSS_PERMITIDAS or not _VALOR_CSS_SEGURO.match(contenido):
            continue
        bajo = contenido.lower()
        if "url(" in bajo or "expression" in bajo or "javascript" in bajo or "@import" in bajo:
            continue
        permitidas.append(f"{propiedad}: {contenido}")
    return "; ".join(permitidas) or None


def _filtrar_atributo(etiqueta: str, atributo: str, valor: str) -> str | None:
    if atributo == "style":
        return _filtrar_css(valor)
    if atributo == "href":
        return valor if _URL_SEGURA.match(valor.strip()) else None
    if atributo == "src":  # solo <img>
        v = valor.strip()
        return valor if (_DATA_IMAGEN.match(v) or v.lower().startswith(("http://", "https://"))) else None
    if atributo in {"width", "height", "colspan", "rowspan", "span"}:
        return valor if _NUMERO.match(valor.strip()) else None
    return valor


def sanitizar_html_enriquecido(html_enriquecido: str) -> str:
    """HTML seguro para insertar con st.markdown(unsafe_allow_html=True)."""
    return nh3.clean(
        html_enriquecido or "",
        tags=TAGS_PERMITIDOS,
        attributes=ATRIBUTOS_PERMITIDOS,
        url_schemes=ESQUEMAS_URL,
        link_rel="noopener noreferrer",
        attribute_filter=_filtrar_atributo,
        strip_comments=True,
    )
