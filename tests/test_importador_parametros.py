"""Tests de scripts/importador_parametros.py: cubre el camino rápido
determinístico (sin llamadas a la API), la escalada al normalizador LLM
(con un cliente falso inyectado -- nunca se llama a la API real), el
reporte de filas descartadas, la advertencia de integridad y el manejo de
errores permanentes vs. transitorios."""
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from scripts.importador_parametros import (
    ErrorImportacionParametros,
    ErrorLLMImportacionParametros,
    importar_parametros,
)


class ClienteLLMFalso:
    """Doble de anthropic.Anthropic(): implementa la misma cadena de
    llamadas que usa _normalizar_bloque_con_llm (`.with_options(...)
    .messages.create(...)`) sin tocar la red. `respuestas` es una cola de
    resultados (uno por bloque/llamada esperada): un dict se serializa
    como el JSON que devolvería la API (según ESQUEMA_SALIDA_LLM); una
    excepción se relanza tal cual, simulando una falla de red/timeout."""

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


def _csv_bytes(texto: str) -> bytes:
    return texto.encode("utf-8-sig")


def test_camino_rapido_dos_columnas_no_llama_al_llm():
    contenido = _csv_bytes("Potencia;100W\nVoltaje;110V\nGabinete;Metálico\n")
    cliente = ClienteLLMFalso(respuestas=[])

    resultado = importar_parametros("parametros.csv", contenido, cliente_llm=cliente)

    assert resultado.camino == "rapido"
    assert cliente.llamadas == 0
    assert resultado.parametros == [
        {"nombre": "Potencia", "valor": "100W"},
        {"nombre": "Voltaje", "valor": "110V"},
        {"nombre": "Gabinete", "valor": "Metálico"},
    ]
    assert resultado.filas_descartadas == []


def test_camino_rapido_conserva_continuacion_multilinea():
    contenido = _csv_bytes(
        "Documentación mínima exigible;Certificado de origen\n;Certificado de calidad\n;Garantía técnica\n"
    )

    resultado = importar_parametros("parametros.csv", contenido, cliente_llm=ClienteLLMFalso([]))

    assert resultado.camino == "rapido"
    assert resultado.parametros == [
        {
            "nombre": "Documentación mínima exigible",
            "valor": "Certificado de origen\nCertificado de calidad\nGarantía técnica",
        }
    ]


def test_archivo_con_celda_combinada_tres_columnas_escala_a_llm_y_fusiona_continuacion():
    # Reproduce el patrón real reportado: columna de categoría que solo
    # aparece llena en la primera fila de cada grupo (celdas combinadas de
    # Excel exportadas a CSV), más una lista de continuación sin nombre.
    contenido = _csv_bytes(
        "Datos Generales;Marca;Acme Corp\n"
        ";Modelo;X-2000\n"
        ";Potencia;500W\n"
        "Documentación;Documentación mínima exigible;Certificado 1\n"
        ";;Certificado 2\n"
        ";;Certificado 3\n"
    )
    respuesta_llm = {
        "parametros": [
            {"parametro": "Marca", "valor": "Acme Corp"},
            {"parametro": "Modelo", "valor": "X-2000"},
            {"parametro": "Potencia", "valor": "500W"},
            {
                "parametro": "Documentación mínima exigible",
                "valor": "Certificado 1\nCertificado 2\nCertificado 3",
            },
        ],
        "descartadas": [],
    }
    cliente = ClienteLLMFalso(respuestas=[respuesta_llm])

    resultado = importar_parametros("parametros.csv", contenido, cliente_llm=cliente)

    assert cliente.llamadas == 1
    assert resultado.camino == "llm"
    assert len(resultado.parametros) == 4
    doc = next(p for p in resultado.parametros if p["nombre"] == "Documentación mínima exigible")
    assert doc["valor"] == "Certificado 1\nCertificado 2\nCertificado 3"


def test_txt_libre_sin_estructura_de_columnas_escala_a_llm():
    contenido = (
        "Parámetro: valor uno sin tabulación\nOtra línea sin separador claro tampoco\n"
    ).encode("utf-8-sig")
    respuesta_llm = {
        "parametros": [{"parametro": "Parámetro", "valor": "valor uno sin tabulación"}],
        "descartadas": [
            {"fila": "Otra línea sin separador claro tampoco", "motivo": "no se pudo interpretar como parámetro"}
        ],
    }
    cliente = ClienteLLMFalso(respuestas=[respuesta_llm])

    resultado = importar_parametros("notas.txt", contenido, cliente_llm=cliente)

    assert cliente.llamadas == 1
    assert resultado.camino == "llm"
    assert resultado.filas_descartadas == [
        {"fila": "Otra línea sin separador claro tampoco", "motivo": "no se pudo interpretar como parámetro"}
    ]


def test_advertencia_integridad_se_dispara_si_el_resultado_difiere_mucho():
    contenido = _csv_bytes(
        "Categoria;Parametro;Valor\n"
        ";Descripción técnica completa del componente;"
        "Un texto bastante largo que describe el componente con mucho detalle tecnico\n"
    )
    # El LLM devuelve un valor truncado/alucinado, muy distinto en longitud al original.
    respuesta_llm = {
        "parametros": [{"parametro": "Descripción técnica completa del componente", "valor": "corto"}],
        "descartadas": [],
    }
    cliente = ClienteLLMFalso(respuestas=[respuesta_llm])

    resultado = importar_parametros("parametros.csv", contenido, cliente_llm=cliente)

    assert resultado.advertencia_integridad is not None


def test_camino_rapido_sin_perdidas_no_dispara_advertencia_integridad():
    contenido = _csv_bytes("Potencia;100W\nVoltaje;110V\n")

    resultado = importar_parametros("parametros.csv", contenido, cliente_llm=ClienteLLMFalso([]))

    assert resultado.advertencia_integridad is None


def test_archivo_vacio_lanza_error_permanente():
    with pytest.raises(ErrorImportacionParametros):
        importar_parametros("vacio.csv", b"", cliente_llm=ClienteLLMFalso([]))


def test_falla_de_red_del_llm_se_relanza_como_error_transitorio():
    contenido = _csv_bytes(
        "Datos Generales;Marca;Acme Corp\n;Modelo;X-2000\n;Potencia;500W\n"
    )
    error_conexion = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    cliente = ClienteLLMFalso(respuestas=[error_conexion])

    with pytest.raises(ErrorLLMImportacionParametros):
        importar_parametros("parametros.csv", contenido, cliente_llm=cliente)
