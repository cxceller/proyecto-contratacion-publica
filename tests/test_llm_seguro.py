"""Controles del respaldo con IA: desactivado por defecto, enmascarado de
datos personales, y validacion/limpieza de la respuesta."""
import pytest

from scripts import importador_items, importador_parametros
from scripts.llm_seguro import (
    RespaldoIADesactivado,
    RespuestaLLMItems,
    RespuestaLLMParametros,
    enmascarar_datos_personales,
    llm_fallback_habilitado,
    preparar_matriz_para_llm,
    validar_respuesta_llm,
)


class TestInterruptor:
    def test_desactivado_por_defecto(self, monkeypatch):
        monkeypatch.delenv("LLM_FALLBACK_ENABLED", raising=False)
        assert not llm_fallback_habilitado()

    @pytest.mark.parametrize("valor", ["false", "0", "", "no", "FALSE"])
    def test_valores_que_no_activan(self, monkeypatch, valor):
        monkeypatch.setenv("LLM_FALLBACK_ENABLED", valor)
        assert not llm_fallback_habilitado()

    @pytest.mark.parametrize("valor", ["true", "TRUE", "1", "yes", "si"])
    def test_valores_que_activan(self, monkeypatch, valor):
        monkeypatch.setenv("LLM_FALLBACK_ENABLED", valor)
        assert llm_fallback_habilitado()

    def test_sin_cliente_y_desactivado_no_se_llama_a_la_api(self, monkeypatch):
        monkeypatch.delenv("LLM_FALLBACK_ENABLED", raising=False)
        matriz_rara = [["texto suelto sin estructura", "otra cosa"], ["x"]]
        with pytest.raises(RespaldoIADesactivado):
            importador_parametros._normalizar_con_llm(matriz_rara)
        with pytest.raises(RespaldoIADesactivado):
            importador_items._normalizar_con_llm(matriz_rara, catalogo_cpc=None)


class TestEnmascarado:
    def test_cedula_ruc_correo_telefono(self):
        t = enmascarar_datos_personales(
            "Juan 0912345678 RUC 1790012345001 mail a.b@x.gob.ec tel +593 99 123 4567"
        )
        assert "0912345678" not in t and "1790012345001" not in t
        assert "a.b@x.gob.ec" not in t and "123 4567" not in t
        assert "[RUC]" in t and "[CORREO]" in t

    def test_no_toca_cpc_de_9_digitos_ni_montos(self):
        assert enmascarar_datos_personales("CPC 012345678 monto 1.234.567,89") == "CPC 012345678 monto 1.234.567,89"

    def test_limita_filas_y_largo_de_celda(self):
        matriz = [["x" * 1000] for _ in range(500)] + [[""]]
        salida = preparar_matriz_para_llm(matriz)
        assert len(salida) == 300 and len(salida[0][0]) == 300

    def test_descarta_filas_vacias(self):
        assert preparar_matriz_para_llm([[""], ["a"], ["  "]]) == [["a"]]


class TestValidacionDeRespuesta:
    def test_respuesta_valida_conserva_saltos_de_linea(self):
        d = validar_respuesta_llm(
            RespuestaLLMParametros,
            r'{"parametros":[{"parametro":"Doc","valor":"a\nb"}],"descartadas":[]}',
        )
        assert d["parametros"][0]["valor"] == "a\nb"

    def test_quita_html_y_caracteres_de_control(self):
        d = validar_respuesta_llm(
            RespuestaLLMParametros,
            r'{"parametros":[{"parametro":"<script>alert(1)</script>Marca","valor":"<b>X</b>\u0000\u200b1"}]}',
        )
        assert "<" not in d["parametros"][0]["parametro"] and "<" not in d["parametros"][0]["valor"]
        assert "\x00" not in d["parametros"][0]["valor"]

    @pytest.mark.parametrize(
        "malo",
        [
            "no es json",
            '{"parametros":"no es lista"}',
            '{"parametros":[{"parametro":123}]}',
            '{"parametros":[{"parametro":"' + "x" * 301 + '"}]}',
        ],
    )
    def test_respuestas_invalidas_se_rechazan_sin_filtrar_contenido(self, malo):
        with pytest.raises(ValueError) as exc:
            validar_respuesta_llm(RespuestaLLMParametros, malo)
        assert "x" * 50 not in str(exc.value)

    def test_items_campos_extra_se_ignoran(self):
        d = validar_respuesta_llm(
            RespuestaLLMItems,
            '{"items":[{"item":"1","cpc":"0123","descripcion":"d","unidad_de_medida":"u",'
            '"cantidad_solicitada":"1","valor_unitario":"2","tipo":"Bien","extra":"x"}],"filas_con_error":[]}',
        )
        assert d["items"][0]["tipo"] == "Bien" and "extra" not in d["items"][0]


class TestRespuestaRAG:
    def test_valida_limpia_y_ignora_extras(self):
        from services.criterio_juridico import RespuestaRAG

        r = RespuestaRAG.model_validate(
            {"explicacion": "<b>Texto</b>\x00 ok", "causal_legal": "Art. 33", "fuentes": ["LOSNCP"], "raro": 1}
        ).model_dump()
        assert r["explicacion"] == "Texto ok" and "raro" not in r

    def test_respuesta_invalida_devuelve_none(self, monkeypatch):
        from services import criterio_juridico

        class R:
            status_code = 200

            def json(self):
                return {"explicacion": 123}

        monkeypatch.setattr(criterio_juridico.requests, "post", lambda *a, **k: R())
        assert criterio_juridico.explicar_desierta("motivo") is None
