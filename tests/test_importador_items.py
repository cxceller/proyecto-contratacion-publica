"""Tests de scripts/importador_items.py: cubre el camino rápido
determinístico (detección de encabezado, fuzzy matching de columnas,
exclusión de "Descripción del CPC"/"Valor Total", filas de TOTAL, celdas
numéricas inválidas), la escalada al normalizador LLM (con un cliente falso
inyectado -- nunca se llama a la API real), el lookup contra un catálogo
CPC falso, y el manejo de errores permanentes vs. transitorios."""
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from scripts.importador_items import (
    ErrorImportacionItems,
    ErrorLLMImportacionItems,
    importar_items,
)


class ClienteLLMFalso:
    """Mismo doble que en tests/test_importador_parametros.py: implementa
    `.with_options(...).messages.create(...)` sin tocar la red."""

    def __init__(self, respuestas: list):
        self._respuestas = list(respuestas)
        self.llamadas = 0

    def with_options(self, **_kwargs):
        return self

    @property
    def messages(self):
        return self

    def create(self, **_kwargs):
        self.llamadas += 1
        dato = self._respuestas.pop(0)
        if isinstance(dato, BaseException):
            raise dato
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(dato))])


CATALOGO_CPC_FALSO = {
    "45111812": "Computadoras portatiles",
    "45121504": "Monitores de video",
    "45121517": "Mouse de computadora",
}


def _csv_bytes(texto: str) -> bytes:
    return texto.encode("utf-8-sig")


def _presupuesto_csv(precio_header: str = "PRECIO UNITARIO") -> bytes:
    return _csv_bytes(
        f"ÍTEM;DESCRIPCION DEL PRODUCTO;UNIDAD;CANTIDAD;{precio_header};CPC;DESCRIPCION DEL CPC;VALOR TOTAL\n"
        "1;Laptop Core i5;Unidad;10;650.00;45111812;Computadoras portatiles;6500.00\n"
        "2;Monitor LED 24 pulgadas;Unidad;10;150.50;45121504;Monitores de video;1505.00\n"
        "3;Mouse inalambrico;Unidad;20;12.99;45121517;Mouse de computadora;259.80\n"
        "TOTAL;;;;;;;8264.80\n"
    )


def test_presupuesto_simple_resuelve_por_camino_rapido_sin_llamar_al_llm():
    cliente = ClienteLLMFalso(respuestas=[])

    resultado = importar_items("Presupuesto Inicial.csv", _presupuesto_csv(), catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=cliente)

    assert resultado.camino == "rapido"
    assert cliente.llamadas == 0
    assert len(resultado.filas) == 3
    descripciones = [f["descripcion"] for f in resultado.filas]
    assert descripciones == ["Laptop Core i5", "Monitor LED 24 pulgadas", "Mouse inalambrico"]


def test_fila_total_se_excluye_y_se_reporta():
    resultado = importar_items(
        "Presupuesto Inicial.csv", _presupuesto_csv(), catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=ClienteLLMFalso([])
    )

    assert not any("TOTAL" in f["descripcion"].upper() for f in resultado.filas)
    motivos = [e["motivo"] for e in resultado.filas_con_error]
    assert any("total" in motivo.lower() for motivo in motivos)


def test_columna_descripcion_del_cpc_y_valor_total_nunca_se_usan():
    resultado = importar_items(
        "Presupuesto Inicial.csv", _presupuesto_csv(), catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=ClienteLLMFalso([])
    )

    # La descripcion de cada fila debe ser la del producto, no la del catalogo CPC
    # (serian identicas por coincidencia en este fixture -- lo que se verifica es
    # que el valor total (6500.00 etc, muy distinto a 650.00) nunca termina en
    # valor_unitario).
    for fila in resultado.filas:
        assert fila["valor_unitario"] < 1000  # el "Valor Total" (miles) nunca se coló ahi


def test_encabezado_con_typo_y_orden_alterado_sigue_resolviendo_por_camino_rapido():
    contenido = _csv_bytes(
        "CPC;PRECIO UNIARIO;CANTIDAD;UNIDAD;DESCRIPCION DEL PRODUCTO;ÍTEM\n"
        "45111812;650.00;10;Unidad;Laptop Core i5;1\n"
        "45121504;150.50;10;Unidad;Monitor LED 24 pulgadas;2\n"
    )
    cliente = ClienteLLMFalso(respuestas=[])

    resultado = importar_items("presupuesto.csv", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=cliente)

    assert resultado.camino == "rapido"
    assert cliente.llamadas == 0
    assert len(resultado.filas) == 2
    assert resultado.filas[0]["valor_unitario"] == 650.0
    assert resultado.filas[0]["numero_cpc"] == "45111812"


def test_celda_cantidad_no_numerica_no_descarta_la_fila():
    contenido = _csv_bytes(
        "ÍTEM;DESCRIPCION DEL PRODUCTO;UNIDAD;CANTIDAD;PRECIO UNITARIO;CPC\n"
        "1;Laptop Core i5;Unidad;diez;650.00;45111812\n"
    )

    resultado = importar_items("presupuesto.csv", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=ClienteLLMFalso([]))

    assert len(resultado.filas) == 1
    assert resultado.filas[0]["cantidad_solicitada"] == 0.0
    assert resultado.filas[0]["descripcion"] == "Laptop Core i5"
    assert any("no numérica" in e["motivo"] for e in resultado.filas_con_error)


def test_cpc_no_encontrado_en_catalogo_se_reporta():
    contenido = _csv_bytes(
        "ÍTEM;DESCRIPCION DEL PRODUCTO;UNIDAD;CANTIDAD;PRECIO UNITARIO;CPC\n"
        "1;Laptop Core i5;Unidad;10;650.00;99999999\n"
    )

    resultado = importar_items("presupuesto.csv", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=ClienteLLMFalso([]))

    assert resultado.cpc_no_encontrados == ["99999999"]
    assert resultado.filas[0]["descripcion_cpc"] == ""


def test_tipo_se_infiere_por_palabra_clave_en_camino_rapido():
    contenido = _csv_bytes(
        "ÍTEM;DESCRIPCION DEL PRODUCTO;UNIDAD;CANTIDAD;PRECIO UNITARIO;CPC\n"
        "1;SUMINISTRO DE LUMINARIA LED;Unidad;10;650.00;45111812\n"
        "2;MANTENIMIENTO PREVENTIVO Y REPOTENCIACIÓN DE TRANSFORMADORES;Servicio;1;500.00;\n"
        "3;Artículo sin ninguna palabra clave reconocible;Unidad;1;1.00;\n"
    )

    resultado = importar_items("presupuesto.csv", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=ClienteLLMFalso([]))

    assert resultado.camino == "rapido"
    assert resultado.filas[0]["tipo"] == "Bien"
    assert resultado.filas[1]["tipo"] == "Servicio"
    assert resultado.filas[2]["tipo"] == ""  # sin coincidencia: el usuario decide a mano


def test_tipo_del_llm_se_usa_cuando_es_valido():
    contenido = "texto libre sin estructura de columnas en absoluto\notra linea cualquiera\n".encode("utf-8-sig")
    respuesta_llm = {
        "items": [
            {
                "item": "1",
                "cpc": "",
                "descripcion": "Reparación de bomba de agua",
                "unidad_de_medida": "Servicio",
                "cantidad_solicitada": "1",
                "valor_unitario": "300.00",
                "tipo": "Servicio",
            }
        ],
        "filas_con_error": [],
    }
    cliente = ClienteLLMFalso(respuestas=[respuesta_llm])

    resultado = importar_items("presupuesto.txt", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=cliente)

    assert resultado.filas[0]["tipo"] == "Servicio"


def test_tipo_del_llm_invalido_cae_a_heuristica_de_palabra_clave():
    contenido = "texto libre sin estructura de columnas en absoluto\notra linea cualquiera\n".encode("utf-8-sig")
    respuesta_llm = {
        "items": [
            {
                "item": "1",
                "cpc": "",
                "descripcion": "SUMINISTRO DE LUMINARIA LED",
                "unidad_de_medida": "Unidad",
                "cantidad_solicitada": "10",
                "valor_unitario": "650.00",
                "tipo": "Bienes",  # valor invalido / fuera del enum -- no deberia pasar nunca en la practica
            }
        ],
        "filas_con_error": [],
    }
    cliente = ClienteLLMFalso(respuestas=[respuesta_llm])

    resultado = importar_items("presupuesto.txt", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=cliente)

    assert resultado.filas[0]["tipo"] == "Bien"


def test_txt_libre_sin_encabezados_reconocibles_escala_a_llm():
    contenido = (
        "Se requiere comprar varios articulos para la oficina segun el siguiente detalle\n"
        "Laptop Core i5, diez unidades, seiscientos cincuenta dolares cada una\n"
        "Monitor LED, diez unidades\n"
    ).encode("utf-8-sig")
    respuesta_llm = {
        "items": [
            {
                "item": "1",
                "cpc": "45111812",
                "descripcion": "Laptop Core i5",
                "unidad_de_medida": "Unidad",
                "cantidad_solicitada": "10",
                "valor_unitario": "650.00",
                "tipo": "Bien",
            }
        ],
        "filas_con_error": [
            {"fila": "Se requiere comprar varios articulos...", "motivo": "fila de título"}
        ],
    }
    cliente = ClienteLLMFalso(respuestas=[respuesta_llm])

    resultado = importar_items("presupuesto.txt", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=cliente)

    assert cliente.llamadas == 1
    assert resultado.camino == "llm"
    assert resultado.filas[0]["descripcion"] == "Laptop Core i5"
    assert resultado.filas[0]["valor_unitario"] == 650.0
    assert resultado.filas[0]["descripcion_cpc"] == "Computadoras portatiles"
    assert any(e["motivo"] == "fila de título" for e in resultado.filas_con_error)


def test_archivo_vacio_lanza_error_permanente():
    with pytest.raises(ErrorImportacionItems):
        importar_items("vacio.csv", b"", catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=ClienteLLMFalso([]))


def test_falla_de_red_del_llm_se_relanza_como_error_transitorio():
    contenido = "texto libre sin estructura de columnas en absoluto\notra linea cualquiera\n".encode("utf-8-sig")
    error_conexion = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    cliente = ClienteLLMFalso(respuestas=[error_conexion])

    with pytest.raises(ErrorLLMImportacionItems):
        importar_items("presupuesto.txt", contenido, catalogo_cpc=CATALOGO_CPC_FALSO, cliente_llm=cliente)
