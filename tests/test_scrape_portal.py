"""Tests unitarios de scripts/scrape_portal.py: por ahora solo cubre las
funciones puras sobre HTML/texto, sin Playwright (_extraer_monto_adjudicado,
_extraer_monto_desde_subtotal, _es_proceso_produccion_nacional,
_extraer_motivo_estado) -- el resto del script depende de una ventana real
de Chromium y no tiene scaffolding de test (ver CLAUDE.md).

Los fixtures de tabla usan <td> (NO <th>) para las filas de encabezado a
proposito: verificado navegando paginas reales de resumenContractual1.cpe/
resumenContractual.cpe con Playwright, el portal dibuja esos encabezados
como filas de datos normales, no como <th> -- pandas.read_html no los
reconoce como encabezado en ese caso (quedan con columnas enteras
0,1,2,...), el mismo quirk que ya resuelve _con_encabezado_valido para la
tabla de resultados de busqueda. Un fixture con <th> no habria detectado
el bug real (encontrado al validar contra HTML real, no sintetico)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scrape_portal import (  # noqa: E402
    _es_proceso_produccion_nacional,
    _extraer_monto_adjudicado,
    _extraer_monto_desde_subtotal,
    _extraer_motivo_estado,
)

# Formato "una fila por adjudicatario" (resumenContractual1.cpe).
HTML_TABLA_SOLO_ADJUDICACION = """
<html><body>
<h2>Información de Adjudicación</h2>
<table>
    <tr><td>#</td><td>RUC</td><td>Nombre del Adjudicatario</td><td>Fecha de Adjudicación</td>
        <td>Monto de Adjudicación ($)</td></tr>
    <tr><td>1</td><td>0912345678001</td><td>PROVEEDOR EJEMPLO S.A.</td><td>2026-01-12</td>
        <td>41,060.00</td></tr>
</table>
</body></html>
"""

HTML_TABLA_MULTIPLES_ADJUDICATARIOS = """
<html><body>
<h2>Información de Adjudicación</h2>
<table>
    <tr><td>#</td><td>RUC</td><td>Nombre del Adjudicatario</td><td>Monto de Adjudicación ($)</td></tr>
    <tr><td>1</td><td>0912345678001</td><td>PROVEEDOR UNO</td><td>10,000.00</td></tr>
    <tr><td>2</td><td>0987654321001</td><td>PROVEEDOR DOS</td><td>5,500.50</td></tr>
</table>
</body></html>
"""

HTML_TABLA_SOLO_CONTRACTUAL = """
<html><body>
<h2>Información del Contrato</h2>
<table>
    <tr><td>#</td><td>RUC</td><td>Razón Social</td><td>Monto Contractual ($)</td></tr>
    <tr><td>1</td><td>0912345678001</td><td>PROVEEDOR EJEMPLO S.A.</td><td>41,060.00</td></tr>
</table>
</body></html>
"""

HTML_TABLA_AMBAS = """
<html><body>
<h2>Información de Adjudicación</h2>
<table>
    <tr><td>#</td><td>RUC</td><td>Nombre del Adjudicatario</td><td>Monto de Adjudicación ($)</td></tr>
    <tr><td>1</td><td>0912345678001</td><td>PROVEEDOR EJEMPLO S.A.</td><td>41,060.00</td></tr>
</table>
<h2>Información del Contrato</h2>
<table>
    <tr><td>#</td><td>RUC</td><td>Razón Social</td><td>Monto Contractual ($)</td></tr>
    <tr><td>1</td><td>0912345678001</td><td>PROVEEDOR EJEMPLO S.A.</td><td>39,500.00</td></tr>
</table>
</body></html>
"""

# Formato "etiqueta: valor" (resumenContractual.cpe, sin el "1"): toda la
# pagina es una unica tabla de dos columnas, con "Monto de Adjudicación"
# (sin "($)") como celda-etiqueta y el valor -- con simbolo "$" y a veces
# repetido en celdas contiguas por colspan -- en la misma fila.
HTML_ETIQUETA_VALOR = """
<html><body>
<table>
    <tr><td>Entidad Contratante</td><td>MUNICIPALIDAD DE GUAYAQUIL</td></tr>
    <tr><td>Tipo de Procedimiento</td><td>Licitación</td></tr>
    <tr><td>Información de Adjudicación</td></tr>
    <tr><td>Nombre del Adjudicatario</td><td>DEVON S.A.</td><td>Tipo:</td><td>JURIDICA</td></tr>
    <tr><td>RUC</td><td>0992265345001</td></tr>
    <tr><td>Fecha de Adjudicación</td><td>2024-11-27</td></tr>
    <tr><td>Monto de Adjudicación</td><td>$ 1,461,355.83</td><td>$ 1,461,355.83</td></tr>
    <tr><td>Información del Contrato Principal</td></tr>
    <tr><td>Monto Contractual</td><td>$ 1,461,355.83</td></tr>
</table>
</body></html>
"""

HTML_ETIQUETA_VALOR_SOLO_CONTRACTUAL = """
<html><body>
<table>
    <tr><td>Entidad Contratante</td><td>MUNICIPALIDAD DE GUAYAQUIL</td></tr>
    <tr><td>Información del Contrato Principal</td></tr>
    <tr><td>Monto Contractual</td><td>$ 1,461,355.83</td></tr>
</table>
</body></html>
"""

HTML_SIN_ADJUDICAR = """
<html><body>
<p>El proceso todavía no tiene adjudicación registrada.</p>
</body></html>
"""


class TestExtraerMontoAdjudicadoFormatoTabla:
    """resumenContractual1.cpe: una tabla con una fila por adjudicatario."""

    def test_una_sola_fila_devuelve_ese_valor(self):
        assert _extraer_monto_adjudicado(HTML_TABLA_SOLO_ADJUDICACION) == 41060.00

    def test_varios_adjudicatarios_suma_los_montos(self):
        assert _extraer_monto_adjudicado(HTML_TABLA_MULTIPLES_ADJUDICATARIOS) == 15500.50

    def test_no_confunde_monto_contractual_con_monto_de_adjudicacion(self):
        # Si solo existe la tabla de "Información del Contrato" (Monto
        # Contractual), NO debe tomar ese valor -- el proceso aun no tiene
        # informacion de adjudicacion.
        assert _extraer_monto_adjudicado(HTML_TABLA_SOLO_CONTRACTUAL) is None

    def test_con_ambas_tablas_toma_exclusivamente_la_de_adjudicacion(self):
        # Ambos montos son distintos a proposito (41060.00 vs 39500.00)
        # para que el test falle si alguna vez se toma la columna
        # equivocada.
        assert _extraer_monto_adjudicado(HTML_TABLA_AMBAS) == 41060.00


class TestExtraerMontoAdjudicadoFormatoEtiquetaValor:
    """resumenContractual.cpe (sin "1"): celda-etiqueta + valor vecino en
    la misma fila, en vez de una tabla con columnas."""

    def test_extrae_el_valor_con_simbolo_de_moneda_y_celdas_repetidas(self):
        assert _extraer_monto_adjudicado(HTML_ETIQUETA_VALOR) == 1461355.83

    def test_no_confunde_monto_contractual_con_monto_de_adjudicacion(self):
        assert _extraer_monto_adjudicado(HTML_ETIQUETA_VALOR_SOLO_CONTRACTUAL) is None


class TestExtraerMontoAdjudicadoCasosLimite:
    def test_proceso_sin_adjudicar_devuelve_none(self):
        assert _extraer_monto_adjudicado(HTML_SIN_ADJUDICAR) is None

    def test_html_vacio_no_lanza_excepcion(self):
        assert _extraer_monto_adjudicado("") is None

    def test_html_sin_tablas_no_lanza_excepcion(self):
        assert _extraer_monto_adjudicado("<html><body><p>Sin tablas</p></body></html>") is None


# Procesos VPN (Verificacion de Produccion Nacional, Cambio 8): no tienen
# fase contractual ni "Resumen de Contrato" -- el monto adjudicado se
# extrae de la columna SubTotal de la tabla "Detalle" en la pagina "Lista
# de Preseleccionados" en su lugar (ver _extraer_monto_desde_subtotal).
HTML_DETALLE_SUBTOTAL_UN_ITEM = """
<html><body>
<h3>CERTIFICADO DE PRODUCCIÓN NACIONAL</h3>
<p>Detalle:</p>
<table>
    <tr><td>Categoría</td><td>Descripción</td><td>Cant.</td><td>Unidad Medida</td>
        <td>Precio Ref. Unitarios</td><td>SubTotal</td></tr>
    <tr><td>Bienes</td><td>Repuestos varios</td><td>10</td><td>Unidad</td>
        <td>41,000.00</td><td>410,000.00</td></tr>
</table>
</body></html>
"""

HTML_DETALLE_SUBTOTAL_VARIOS_ITEMS = """
<html><body>
<p>Detalle:</p>
<table>
    <tr><td>Categoría</td><td>Descripción</td><td>Cant.</td><td>Unidad Medida</td>
        <td>Precio Ref. Unitarios</td><td>SubTotal</td></tr>
    <tr><td>Bienes</td><td>Item uno</td><td>5</td><td>Unidad</td><td>1,000.00</td><td>5,000.00</td></tr>
    <tr><td>Bienes</td><td>Item dos</td><td>2</td><td>Unidad</td><td>2,500.00</td><td>5,000.00</td></tr>
</table>
</body></html>
"""

HTML_SIN_COLUMNA_SUBTOTAL = """
<html><body>
<table>
    <tr><td>Categoría</td><td>Descripción</td><td>Monto Contractual ($)</td></tr>
    <tr><td>Bienes</td><td>Item</td><td>10,000.00</td></tr>
</table>
</body></html>
"""


class TestEsProcesoProduccionNacional:
    def test_codigo_con_prefijo_vpn_es_produccion_nacional(self):
        assert _es_proceso_produccion_nacional("VPN-MIMG-2026-001") is True

    def test_codigo_con_prefijo_vpn_minuscula_tambien_cuenta(self):
        assert _es_proceso_produccion_nacional("vpn-mimg-2026-001") is True

    def test_codigo_con_espacios_alrededor_tambien_cuenta(self):
        assert _es_proceso_produccion_nacional("  VPN-MIMG-2026-001  ") is True

    def test_codigo_de_otro_tipo_de_proceso_no_es_produccion_nacional(self):
        assert _es_proceso_produccion_nacional("SIE-MIMG-2026-022") is False


class TestExtraerMontoDesdeSubtotal:
    def test_un_solo_item_devuelve_su_subtotal(self):
        assert _extraer_monto_desde_subtotal(HTML_DETALLE_SUBTOTAL_UN_ITEM) == 410000.00

    def test_varios_items_suma_los_subtotales(self):
        assert _extraer_monto_desde_subtotal(HTML_DETALLE_SUBTOTAL_VARIOS_ITEMS) == 10000.00

    def test_sin_columna_subtotal_devuelve_none(self):
        assert _extraer_monto_desde_subtotal(HTML_SIN_COLUMNA_SUBTOTAL) is None

    def test_html_vacio_no_lanza_excepcion(self):
        assert _extraer_monto_desde_subtotal("") is None

    def test_html_sin_tablas_no_lanza_excepcion(self):
        assert _extraer_monto_desde_subtotal("<html><body><p>Sin tablas</p></body></html>") is None


# Cambio 10: capturar el texto completo (Razon/Fecha/Justificacion) de la
# celda "Estado del Proceso" de la pagina GENERAL de detalle -- no solo la
# etiqueta corta del estado.
HTML_ESTADO_PROCESO_DESIERTA = """
<html><body>
<table>
<tr><td>Entidad Contratante:</td><td>MUNICIPALIDAD DE GUAYAQUIL</td></tr>
<tr><td>Estado del Proceso:</td>
    <td>
        <div>Desierta</div>
        <div>Razón: Por haber sido inhabilitadas las ofertas presentadas.</div>
        <div>Fecha: 2026-05-20</div>
        <div>Justificación: Art. 33 de la LOSNCP.</div>
    </td>
</tr>
</table>
</body></html>
"""

HTML_ESTADO_PROCESO_MAYUSCULAS = """
<html><body>
<table>
<tr><td>ESTADO DEL PROCESO:</td><td>Adjudicado - Registro de Contratos</td></tr>
</table>
</body></html>
"""

HTML_SIN_FILA_ESTADO_PROCESO = """
<html><body>
<table>
<tr><td>Entidad Contratante:</td><td>MUNICIPALIDAD DE GUAYAQUIL</td></tr>
</table>
</body></html>
"""

HTML_FILA_ESTADO_PROCESO_SIN_SEGUNDA_CELDA = """
<html><body>
<table>
<tr><td>Estado del Proceso:</td></tr>
</table>
</body></html>
"""


class TestExtraerMotivoEstado:
    def test_extrae_texto_completo_con_razon_fecha_y_justificacion(self):
        texto = _extraer_motivo_estado(HTML_ESTADO_PROCESO_DESIERTA)
        assert texto == (
            "Desierta\n"
            "Razón: Por haber sido inhabilitadas las ofertas presentadas.\n"
            "Fecha: 2026-05-20\n"
            "Justificación: Art. 33 de la LOSNCP."
        )

    def test_encuentra_la_etiqueta_sin_importar_mayusculas(self):
        assert _extraer_motivo_estado(HTML_ESTADO_PROCESO_MAYUSCULAS) == "Adjudicado - Registro de Contratos"

    def test_sin_fila_estado_del_proceso_devuelve_none(self):
        assert _extraer_motivo_estado(HTML_SIN_FILA_ESTADO_PROCESO) is None

    def test_fila_sin_segunda_celda_devuelve_none(self):
        assert _extraer_motivo_estado(HTML_FILA_ESTADO_PROCESO_SIN_SEGUNDA_CELDA) is None

    def test_html_vacio_no_lanza_excepcion(self):
        assert _extraer_motivo_estado("") is None

    def test_html_sin_tablas_no_lanza_excepcion(self):
        assert _extraer_motivo_estado("<html><body><p>Sin tablas</p></body></html>") is None
