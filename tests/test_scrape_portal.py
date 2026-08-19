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
    _es_proceso_licitacion,
    _es_proceso_produccion_nacional,
    _extraer_monto_adjudicado,
    _extraer_monto_desde_subtotal,
    _extraer_monto_licitacion,
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
