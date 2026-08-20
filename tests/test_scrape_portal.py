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
    _es_proceso_consultoria,
    _es_proceso_licitacion,
    _es_proceso_produccion_nacional,
    _es_proceso_subasta_inversa,
    _extraer_monto_adjudicado,
    _extraer_monto_consultoria,
    _extraer_monto_desde_subtotal,
    _extraer_monto_licitacion,
    _extraer_motivo_estado,
    _extraer_valor_oferta_mas_baja,
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


class TestEsProcesoLicitacion:
    def test_codigo_lico_es_licitacion(self):
        assert _es_proceso_licitacion("LICO-MIMG-2026-002") is True

    def test_codigo_lics_es_licitacion(self):
        assert _es_proceso_licitacion("LICS-MIMG-2026-008") is True

    def test_codigo_licb_es_licitacion(self):
        assert _es_proceso_licitacion("LICB-MIMG-2026-005") is True

    def test_codigo_en_minuscula_tambien_cuenta(self):
        assert _es_proceso_licitacion("lics-mimg-2026-008") is True

    def test_codigo_con_espacios_alrededor_tambien_cuenta(self):
        assert _es_proceso_licitacion("  LICS-MIMG-2026-008  ") is True

    def test_codigo_de_otro_tipo_de_proceso_no_es_licitacion(self):
        assert _es_proceso_licitacion("SIE-MIMG-2026-022") is False

    def test_codigo_vpn_no_es_licitacion(self):
        assert _es_proceso_licitacion("VPN-MIMG-2026-001") is False


# Fragmentos derivados de un volcado REAL de resumenAdjudicacion.cpe
# (proceso LICS-MIMG-2026-008, Monto Adjudicado real confirmado en el
# portal: $87.600,00) -- ambas tablas traen columna Subtotal/SubTotal, lo
# que las hace indistinguibles por esa columna sola; ver
# _tabla_resultados_licitacion_adjudicados sobre como se distinguen. Nota:
# el portal usa una capitalizacion DISTINTA para esa columna en cada tabla
# ("SubTotal" en la referencial, "Subtotal" en la de adjudicados) -- a
# proposito no se normaliza aca, para poder detectar una regresion si
# _tabla_resultados_licitacion_adjudicados alguna vez asumiera un literal
# fijo (ver el comentario en esa funcion).
HTML_LICITACION_TABLA_REFERENCIAL = """
<table width="100%" border="1" cellspacing="0" cellpadding="0" class="licitacion_contenido_texto">
    <tbody><tr>
        <td class="filaTitulo"><div align="center">Categoría</div></td>
        <td class="filaTitulo"><div align="center">Bien/Obra/Servicio</div></td>
        <td class="filaTitulo"><div align="center">Cant.</div></td>
        <td class="filaTitulo"><div align="center">Unidad Medida</div></td>
        <td class="filaTitulo"><div align="center">Precio Ref. Unitarios</div></td>
        <td class="filaTitulo"><div align="center">SubTotal</div></td>
    </tr>
    <tr>
        <td>836100011</td>
        <td>SERVICIOS DE PLANIFICACION</td>
        <td>1</td>
        <td>Unidad</td>
        <td align="right">USD 87,644.81</td>
        <td align="right">USD 87,644.81</td>
    </tr>
</tbody></table>
"""

HTML_LICITACION_TABLA_ADJUDICADOS = """
<table width="100%" border="0" cellpadding="2" cellspacing="0">
    <tbody><tr>
        <td class="bordeCompleto filaTitulo"><div align="center">Categoría</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Descripción Bien/Obra/Servicio</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Proveedor</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Cantidad Adjudicada</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Precio Unitario</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Subtotal</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Tiempo de Entrega</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Razón Adjudicación</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Estado</div></td>
    </tr>
    <tr>
        <td class="bordeCompleto filaTitulo2">836100011</td>
        <td class="bordeCompleto filaTitulo2">SERVICIOS DE PLANIFICACION</td>
        <td class="bordeCompleto filaTitulo2">COMIC CITY S.A.S.</td>
        <td class="bordeCompleto filaTitulo2" align="center">1</td>
        <td class="bordeCompleto filaTitulo2" align="center">USD 87,600.00</td>
        <td class="bordeCompleto filaTitulo2" align="center">USD 87,600.00</td>
        <td class="bordeCompleto filaTitulo2" align="center">20</td>
        <td class="bordeCompleto filaTitulo2">POR SER IDÓNEA</td>
        <td class="bordeCompleto filaTitulo2">Adjudicado</td>
    </tr>
</tbody></table>
"""

HTML_LICITACION_TABLA_ADJUDICADOS_VARIOS_LOTES = """
<table width="100%" border="0" cellpadding="2" cellspacing="0">
    <tbody><tr>
        <td class="bordeCompleto filaTitulo"><div align="center">Categoría</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Descripción Bien/Obra/Servicio</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Proveedor</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Cantidad Adjudicada</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Precio Unitario</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Subtotal</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Razón Adjudicación</div></td>
        <td class="bordeCompleto filaTitulo"><div align="center">Estado</div></td>
    </tr>
    <tr>
        <td>1</td><td>Lote uno</td><td>Proveedor A</td><td>1</td>
        <td align="center">USD 10,000.00</td><td align="center">USD 10,000.00</td>
        <td>Motivo A</td><td>Adjudicado</td>
    </tr>
    <tr>
        <td>2</td><td>Lote dos</td><td>Proveedor B</td><td>1</td>
        <td align="center">USD 5,500.50</td><td align="center">USD 5,500.50</td>
        <td>Motivo B</td><td>Adjudicado</td>
    </tr>
</tbody></table>
"""

HTML_RESUMEN_ADJUDICACION_AMBAS_TABLAS = (
    "<html><body>" + HTML_LICITACION_TABLA_REFERENCIAL + HTML_LICITACION_TABLA_ADJUDICADOS + "</body></html>"
)

# Estado real de un proceso "Adjudicado - Registro de Contratos" cuyo
# contrato aun no se registra: resumenAdjudicacion.cpe SI existe y trae la
# tabla referencial, pero la de "Bien/Obra/Servicio Adjudicados" todavia no
# se publica -- debe devolver None, NUNCA el valor referencial.
HTML_RESUMEN_ADJUDICACION_SOLO_REFERENCIAL = "<html><body>" + HTML_LICITACION_TABLA_REFERENCIAL + "</body></html>"


class TestExtraerMontoLicitacion:
    def test_toma_la_tabla_de_adjudicados_no_la_referencial(self):
        assert _extraer_monto_licitacion(HTML_RESUMEN_ADJUDICACION_AMBAS_TABLAS) == 87600.00
        assert _extraer_monto_licitacion(HTML_RESUMEN_ADJUDICACION_AMBAS_TABLAS) != 87644.81

    def test_varios_lotes_suma_los_subtotales_adjudicados(self):
        html = "<html><body>" + HTML_LICITACION_TABLA_ADJUDICADOS_VARIOS_LOTES + "</body></html>"
        assert _extraer_monto_licitacion(html) == 15500.50

    def test_solo_tabla_referencial_sin_adjudicados_devuelve_none(self):
        # Nunca debe caer de vuelta al valor referencial (87644.81).
        assert _extraer_monto_licitacion(HTML_RESUMEN_ADJUDICACION_SOLO_REFERENCIAL) is None

    def test_html_vacio_no_lanza_excepcion(self):
        assert _extraer_monto_licitacion("") is None

    def test_html_sin_tablas_no_lanza_excepcion(self):
        assert _extraer_monto_licitacion("<html><body><p>Sin tablas</p></body></html>") is None


class TestEsProcesoSubastaInversa:
    def test_codigo_sie_es_subasta_inversa(self):
        assert _es_proceso_subasta_inversa("SIE-MIMG-2026-021") is True

    def test_codigo_en_minuscula_tambien_cuenta(self):
        assert _es_proceso_subasta_inversa("sie-mimg-2026-021") is True

    def test_codigo_con_espacios_alrededor_tambien_cuenta(self):
        assert _es_proceso_subasta_inversa("  SIE-MIMG-2026-021  ") is True

    def test_codigo_lic_no_es_subasta_inversa(self):
        assert _es_proceso_subasta_inversa("LICS-MIMG-2026-008") is False

    def test_codigo_vpn_no_es_subasta_inversa(self):
        assert _es_proceso_subasta_inversa("VPN-MIMG-2026-001") is False

    def test_codigo_cpc_no_es_subasta_inversa(self):
        assert _es_proceso_subasta_inversa("CPC-MIMG-2026-002") is False


# Fragmento derivado de un volcado REAL de ResumenPuja.cpe (proceso
# SIE-MIMG-2026-021, llegado por clic en sesion desde su ficha general --
# esa pagina NO se puede pedir por URL directa "en frio", redirige a login,
# ver _ir_a_resumen_resultados_subasta). El "Monto de Adjudicacion" real
# ahi NO usa esa etiqueta literal -- usa "Valor Adjudicado" (confirmado
# contra la pagina real), que ya esta en ETIQUETAS_MONTO_ADJUDICADO, asi
# que _extraer_monto_adjudicado (sin ningun cambio) ya lo resuelve via el
# formato "etiqueta: valor en la misma fila"
# (_valores_monto_adjudicacion_en_celdas) -- no hizo falta un extractor
# nuevo. Monto Adjudicado real confirmado en el portal: $80.000,00.
HTML_RESUMEN_PUJA_REAL = """
<html><body>
<table width="100%" border="1" cellpadding="0" cellspacing="0" id="tableadjudicacion">
<tr><td class="filaTitulo"><div align="center">El proveedor Adjudicado es: </div></td>
    <td class="filaTitulo"><div align="center">KINGRIVER S.A.</div></td></tr>
<tr><td class="textoAzul">Valor Adjudicado </td>
    <td><div align="center" class="textoAzul12">USD 80,000.00</div></td></tr>
<tr><td class="textoAzul">Razón de adjudicación</td>
    <td><div align="center" class="textoAzul12">Por ser idónea desde el punto de vista jurídico.</div></td></tr>
</table>
</body></html>
"""


# Mismo volcado real, pero de un SIE resuelto por NEGOCIACION en vez de
# puja (proceso SIE-MIMG-2026-002, llegado por el enlace "Ver Resultados de
# Negociación" -- ver _CANDIDATOS_ENLACE_RESULTADOS_SUBASTA): misma pagina
# ResumenPuja.cpe, misma plantilla de tabla y misma etiqueta "Valor
# Adjudicado" que el caso de Subasta -- confirma que _extraer_monto_adjudicado
# resuelve ambos casos sin cambios. Monto Adjudicado real confirmado en el
# portal: $37.000,00.
HTML_RESUMEN_PUJA_REAL_NEGOCIACION = """
<html><body>
<table width="100%" border="1" cellpadding="0" cellspacing="0" id="tableadjudicacion">
<tr><td class="filaTitulo"><div align="center">El proveedor Adjudicado es: </div></td>
    <td class="filaTitulo"><div align="center">RUEDA PACHECO WALTER HERNAN</div></td></tr>
<tr><td class="textoAzul">Valor Adjudicado </td>
    <td><div align="center" class="textoAzul12">USD 37,000.00</div></td></tr>
<tr><td class="textoAzul">Razón de adjudicación</td>
    <td><div align="center" class="textoAzul12">Por ser idónea desde el punto de vista jurídico.</div></td></tr>
</table>
</body></html>
"""


class TestExtraerMontoAdjudicadoResumenPujaReal:
    """No es un extractor nuevo: _extraer_monto_adjudicado ya cubre este
    formato (etiqueta + valor en la misma fila, ver
    TestExtraerMontoAdjudicadoFormatoEtiquetaValor mas abajo) -- esta clase
    solo blinda que sigue funcionando contra el HTML REAL de
    ResumenPuja.cpe (no un sintetico), con su etiqueta real "Valor
    Adjudicado" en vez de "Monto de Adjudicación", tanto si el proceso se
    resolvio por Subasta como por Negociacion (misma pagina, mismo
    formato)."""

    def test_extrae_el_valor_adjudicado_real_de_resumen_puja_subasta(self):
        assert _extraer_monto_adjudicado(HTML_RESUMEN_PUJA_REAL) == 80000.00

    def test_extrae_el_valor_adjudicado_real_de_resumen_puja_negociacion(self):
        assert _extraer_monto_adjudicado(HTML_RESUMEN_PUJA_REAL_NEGOCIACION) == 37000.00


class TestEsProcesoConsultoria:
    def test_codigo_cpc_es_consultoria(self):
        assert _es_proceso_consultoria("CPC-MIMG-2026-002") is True

    def test_codigo_en_minuscula_tambien_cuenta(self):
        assert _es_proceso_consultoria("cpc-mimg-2026-002") is True

    def test_codigo_con_espacios_alrededor_tambien_cuenta(self):
        assert _es_proceso_consultoria("  CPC-MIMG-2026-002  ") is True

    def test_codigo_lcc_es_consultoria(self):
        assert _es_proceso_consultoria("LCC-MIMG-2025-007") is True

    def test_codigo_lcc_en_minuscula_tambien_cuenta(self):
        assert _es_proceso_consultoria("lcc-mimg-2025-007") is True

    def test_codigo_sie_no_es_consultoria(self):
        assert _es_proceso_consultoria("SIE-MIMG-2026-021") is False

    def test_codigo_lic_no_es_consultoria(self):
        assert _es_proceso_consultoria("LICS-MIMG-2026-008") is False

    def test_codigo_vpn_no_es_consultoria(self):
        assert _es_proceso_consultoria("VPN-MIMG-2026-001") is False


# Fragmentos derivados de un volcado REAL de resumenAdjudicacionConsultoria.cpe
# (proceso CPC-MIMG-2026-002, llegado por clic en sesion desde su ficha
# general, pestaña "Fechas" -> "Ver Adjudicación Consultoría"). Monto
# Adjudicado real confirmado en el portal: $172.495,04 (Precio Negociación),
# NUNCA el referencial $179.501,77 (SubTotal de "Detalle: Consultoría").
HTML_CONSULTORIA_TABLA_REFERENCIAL = """
<table width="99%" border="1" cellspacing="0" cellpadding="0">
    <tbody><tr>
        <td class="filaTitulo"><div align="center">Categoría</div></td>
        <td class="filaTitulo"><div align="center">Consultoría</div></td>
        <td class="filaTitulo"><div align="center">Cant.</div></td>
        <td class="filaTitulo"><div align="center">Unidad Medida</div></td>
        <td class="filaTitulo"><div align="center">Precio Ref. Unitarios</div></td>
        <td class="filaTitulo"><div align="center">SubTotal</div></td>
    </tr>
    <tr>
        <td>832210117</td>
        <td>SERVICIOS DE URBANISMO Y PLANIFICACION</td>
        <td>1</td>
        <td>Unidad</td>
        <td>USD 179501.7700</td>
        <td>USD 179,501.77</td>
    </tr>
</tbody></table>
"""

HTML_CONSULTORIA_TABLA_ADJUDICADOS = """
<table width="100%" border="1" cellpadding="0" cellspacing="0" class="licitacion_contenido_texto">
    <tbody><tr>
        <td class="licitacion_titulos"><div align="center">Producto</div></td>
        <td class="licitacion_titulos"><div align="center">Descripción Consultoría</div></td>
        <td class="licitacion_titulos"><div align="center">Proveedor</div></td>
        <td class="licitacion_titulos"><div align="center">Cantidad</div></td>
        <td class="licitacion_titulos"><div align="center">Precio Ofertado</div></td>
        <td class="licitacion_titulos"><div align="center">Plazo Ofertado</div></td>
        <td class="licitacion_titulos"><div align="center">Precio Negociación</div></td>
        <td class="licitacion_titulos"><div align="center">Tiempo de Entrega</div></td>
        <td class="licitacion_titulos"><div align="center">Razón Adjudicación</div></td>
        <td class="licitacion_titulos"><div align="center">Estado</div></td>
        <td class="licitacion_titulos"><div align="center">Acción</div></td>
    </tr>
    <tr>
        <td>832210117</td>
        <td>SERVICIOS DE URBANISMO Y PLANIFICACION</td>
        <td>J&amp;JH INTERNATIONAL CONSULTING CIA. LTDA.</td>
        <td>1</td>
        <td>178000</td>
        <td>150</td>
        <td>172495.04</td>
        <td>150</td>
        <td>De conformidad con el Art. 355 num. 2 del RGLOSNCP.</td>
        <td>Adjudicado</td>
        <td></td>
    </tr>
</tbody></table>
"""

HTML_RESUMEN_ADJUDICACION_CONSULTORIA_AMBAS_TABLAS = (
    "<html><body>" + HTML_CONSULTORIA_TABLA_REFERENCIAL + HTML_CONSULTORIA_TABLA_ADJUDICADOS + "</body></html>"
)

# Estado real de un CPC "Adjudicado - Registro de Contratos" cuyo contrato
# aun no se registra: resumenAdjudicacionConsultoria.cpe SI existe y trae
# la tabla referencial, pero la de "Consultoría Adjudicados" todavia no se
# publica -- debe devolver None, NUNCA el valor referencial.
HTML_RESUMEN_ADJUDICACION_CONSULTORIA_SOLO_REFERENCIAL = (
    "<html><body>" + HTML_CONSULTORIA_TABLA_REFERENCIAL + "</body></html>"
)


class TestExtraerMontoConsultoria:
    def test_toma_precio_negociacion_no_el_subtotal_referencial(self):
        assert _extraer_monto_consultoria(HTML_RESUMEN_ADJUDICACION_CONSULTORIA_AMBAS_TABLAS) == 172495.04
        assert _extraer_monto_consultoria(HTML_RESUMEN_ADJUDICACION_CONSULTORIA_AMBAS_TABLAS) != 179501.77

    def test_solo_tabla_referencial_sin_adjudicados_devuelve_none(self):
        assert _extraer_monto_consultoria(HTML_RESUMEN_ADJUDICACION_CONSULTORIA_SOLO_REFERENCIAL) is None

    def test_html_vacio_no_lanza_excepcion(self):
        assert _extraer_monto_consultoria("") is None

    def test_html_sin_tablas_no_lanza_excepcion(self):
        assert _extraer_monto_consultoria("<html><body><p>Sin tablas</p></body></html>") is None


# Fragmentos derivados de un volcado REAL de resumenAdjudicacionConsultoria.cpe
# de un proceso LCC (Lista Corta de Consultoria, proceso LCC-MIMG-2025-007):
# misma plantilla exacta que CPC (mismas columnas, mismo formato de fila).
# Monto Adjudicado real confirmado en el portal: $82.013,52 (Precio
# Negociación) -- NI el referencial $100.572,64 (SubTotal de "Detalle:
# Consultoría") NI el "Precio Ofertado" $82.591,46 (la oferta ANTES de
# negociar, ver tambien HTML_EVALUACION_FINAL_LCC_REAL mas abajo).
HTML_CONSULTORIA_ADJUDICADOS_LCC_REAL = """
<table width="100%" border="1" cellpadding="0" cellspacing="0" class="licitacion_contenido_texto">
    <tbody><tr>
        <td class="licitacion_titulos"><div align="center">Producto</div></td>
        <td class="licitacion_titulos"><div align="center">Descripción Consultoría</div></td>
        <td class="licitacion_titulos"><div align="center">Proveedor</div></td>
        <td class="licitacion_titulos"><div align="center">Cantidad</div></td>
        <td class="licitacion_titulos"><div align="center">Precio Ofertado</div></td>
        <td class="licitacion_titulos"><div align="center">Plazo Ofertado</div></td>
        <td class="licitacion_titulos"><div align="center">Precio Negociación</div></td>
        <td class="licitacion_titulos"><div align="center">Tiempo de Entrega</div></td>
        <td class="licitacion_titulos"><div align="center">Razón Adjudicación</div></td>
        <td class="licitacion_titulos"><div align="center">Estado</div></td>
        <td class="licitacion_titulos"><div align="center">Acción</div></td>
    </tr>
    <tr>
        <td>839900114</td>
        <td>FISCALIZACION DE OBRAS Y SERVICIOS</td>
        <td>CHICA GARCIA DANIEL EDUARDO</td>
        <td>1</td>
        <td>82591.46</td>
        <td>720</td>
        <td>82013.52</td>
        <td>720</td>
        <td>De conformidad con los pliegos.</td>
        <td>Adjudicado</td>
        <td></td>
    </tr>
</tbody></table>
"""


class TestExtraerMontoConsultoriaLCC:
    """Blinda que la misma funcion (sin cambios) resuelve tambien Lista
    Corta de Consultoria (LCC), no solo Concurso Publico (CPC) -- misma
    plantilla de pagina, confirmado contra un proceso real."""

    def test_toma_precio_negociacion_no_ofertado_ni_referencial(self):
        html = "<html><body>" + HTML_CONSULTORIA_ADJUDICADOS_LCC_REAL + "</body></html>"
        resultado = _extraer_monto_consultoria(html)
        assert resultado == 82013.52
        assert resultado != 100572.64  # referencial
        assert resultado != 82591.46  # precio ofertado (antes de negociar)


# Fragmento derivado de un volcado REAL de
# resumenCalificacionFinalConsultoria.cpe ("Ver evaluación final") del
# mismo proceso LCC-MIMG-2025-007 -- pagina de RESPALDO, solo se usa
# cuando "Precio Negociación" todavia no existe (ver
# _ir_a_evaluacion_final_consultoria). "VALOR DE LA OFERTA MÁS BAJA" real
# confirmado en el portal: $82.591,46 (la oferta antes de negociar --
# ojo, DISTINTO del Precio Negociación final $82.013,52).
HTML_EVALUACION_FINAL_LCC_REAL = """
<html><body>
<table>
<tr><td align="left">VALOR DE LA OFERTA MÁS BAJA</td><td align="left">82591.46</td></tr>
</table>
</body></html>
"""

HTML_EVALUACION_FINAL_SIN_ETIQUETA = """
<html><body>
<table><tr><td>Otra fila</td><td>Sin relacion</td></tr></table>
</body></html>
"""


class TestExtraerValorOfertaMasBaja:
    def test_extrae_el_valor_real_de_la_oferta_mas_baja(self):
        assert _extraer_valor_oferta_mas_baja(HTML_EVALUACION_FINAL_LCC_REAL) == 82591.46

    def test_sin_la_etiqueta_devuelve_none(self):
        assert _extraer_valor_oferta_mas_baja(HTML_EVALUACION_FINAL_SIN_ETIQUETA) is None

    def test_html_vacio_no_lanza_excepcion(self):
        assert _extraer_valor_oferta_mas_baja("") is None

    def test_html_sin_tablas_no_lanza_excepcion(self):
        assert _extraer_valor_oferta_mas_baja("<html><body><p>Sin tablas</p></body></html>") is None


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


# Fragmento derivado de un volcado REAL de una pagina de detalle
# (informacionProcesoContratacion2.cpe, proceso LICO-MIMG-2026-002, capturado
# con Playwright dejando pasar tiempo suficiente para que el bloque de
# `<table>` que arma `activeTab()` en el onload ya este renderizado -- ver
# TIMEOUT_MOTIVO_ESTADO_MS en scrape_portal.py). A diferencia de los
# fixtures sinteticos de arriba (que usan `<td>etiqueta</td><td>valor</td>`),
# la fila real usa `<th>etiqueta</th><td>valor</td>` -- un patron que los
# fixtures sinteticos nunca ejercitaron.
HTML_ESTADO_PROCESO_TABLA_REAL = """
<html><body>
<table>
<tr><th>Tipo de Contratación:</th><td>Licitación - </td></tr>
<tr><th>Forma de Pago:</th><td>Anticipo: 20% Saldo:  80.00%</td></tr>
<tr><th>Plazo de Entrega:</th><td>360 dias</td></tr>
<tr><th>Vigencia de Oferta:</th><td>90 días</td></tr>
<tr><th>Funcionario encargado del proceso:</th><td>gdominguezi@guayaquil.gov.ec</td></tr>
<tr><th>Estado del Proceso:</th><td> <strong>Adjudicado - Registro de Contratos</strong></td></tr>
<tr><th>Descripción:</th><td>MANTENIMIENTO VIAL CON PAVIMENTO DE HORMIGÓN</td></tr>
</table>
</body></html>
"""

# Mismo fragmento real, pero capturado ANTES de que `activeTab()` termine de
# renderizar la tabla (equivalente al dump temprano real, t=0): la fila
# "Estado del Proceso" -- de hecho la tabla entera -- todavia no existe.
HTML_TABLA_AUN_NO_RENDERIZADA = """
<html><body>
<div id="tabContenido"></div>
</body></html>
"""


class TestExtraerMotivoEstadoConHtmlRealThTd:
    """Cubre el patron `<th>etiqueta</th><td>valor</td>` de la pagina de
    detalle real (ver HTML_ESTADO_PROCESO_TABLA_REAL) -- los fixtures
    sinteticos de TestExtraerMotivoEstado de mas abajo usan `<td><td>` y
    nunca ejercitaron este caso."""

    def test_extrae_estado_de_fila_con_th_y_td(self):
        assert _extraer_motivo_estado(HTML_ESTADO_PROCESO_TABLA_REAL) == "Adjudicado - Registro de Contratos"

    def test_tabla_aun_no_renderizada_devuelve_none(self):
        assert _extraer_motivo_estado(HTML_TABLA_AUN_NO_RENDERIZADA) is None


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
