from app_ui import ESTADOS_FUGA_PIPELINE, ETAPAS_PIPELINE_CONTRATACION, _conteos_por_estado


def test_orden_real_del_flujo_sercop():
    e = ETAPAS_PIPELINE_CONTRATACION
    assert e[0] == "Preguntas, Respuestas y Aclaraciones" and e[-1] == "Finalizada"
    assert e.index("Entrega de Propuesta") < e.index("Convalidación de Errores") < e.index("Por Adjudicar")
    assert e.index("Adjudicada") < e.index("Ejecución de Contrato") < e.index("En Recepción") < e.index("Finalizada")


def test_las_fugas_no_son_etapas():
    assert not set(ESTADOS_FUGA_PIPELINE) & set(ETAPAS_PIPELINE_CONTRATACION)
    assert "Desierta" in ESTADOS_FUGA_PIPELINE


def test_conteos_ignoran_tildes_mayusculas_y_vacios():
    c = _conteos_por_estado(
        [{"estado": "Ejecución de Contrato"}, {"estado": "EJECUCION DE CONTRATO "}, {"estado": ""}, {"estado": None}, {}]
    )
    assert c == {"EJECUCION DE CONTRATO": 2}
