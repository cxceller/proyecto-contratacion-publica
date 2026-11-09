"""Seguridad de src/database.py y de los parametros de GET /api/todos:
LIKE con comodines escapados, lista blanca de columnas, topes de longitud."""
import pytest

from src import database


def _crear(codigo, estado="Adjudicada", palabra="luminarias"):
    database.insert_contratacion(
        {
            "codigo": codigo,
            "entidad_contratante": "E",
            "objeto_proceso": "o",
            "estado": estado,
            "palabra_clave": palabra,
            "provincia_canton": None,
            "presupuesto_referencial": 1.0,
            "fecha_publicacion": "2025-01-10",
            "url": None,
            "lote_id": None,
            "monto_adjudicado": None,
            "motivo_estado_raw": None,
            "explicacion_estado": None,
        }
    )


@pytest.fixture()
def bd(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"))
    database.init_db()
    _crear("A-1", estado="Adjudicada", palabra="luminarias")
    _crear("A-2", estado="Desierta", palabra="100% led")
    _crear("A-3", estado="Cancelado", palabra="alumbrado_publico")
    return database


class TestLikeEscapado:
    def test_escapar_like(self):
        assert database._escapar_like("a%b_c\\d") == "a\\%b\\_c\\\\d"

    def test_porcentaje_en_estado_no_es_comodin(self, bd):
        assert bd.get_all_contrataciones(status="%") == []

    def test_guion_bajo_en_palabra_clave_no_es_comodin(self, bd):
        # "alumbrado_publico" con "_" literal: encuentra solo esa fila,
        # y "alumbradoXpublico" (comodin) ya no la encontraria.
        assert [r["codigo"] for r in bd.get_all_contrataciones(palabra_clave="alumbrado_publico")] == ["A-3"]
        assert bd.get_all_contrataciones(palabra_clave="alumbrado_") == [
            r for r in bd.get_all_contrataciones() if r["codigo"] == "A-3"
        ]

    def test_porcentaje_literal_en_palabra_clave(self, bd):
        assert [r["codigo"] for r in bd.get_all_contrataciones(palabra_clave="100% led")] == ["A-2"]

    def test_solo_comodines_no_traen_todo(self, bd):
        assert bd.get_all_contrataciones(palabra_clave="%%%%") == []
        assert bd.get_all_contrataciones(palabra_clave="____") == []

    def test_busqueda_normal_sigue_funcionando_insensible_a_tildes_y_mayusculas(self, bd):
        assert len(bd.get_all_contrataciones(palabra_clave="LUMINARIAS")) == 1
        assert len(bd.get_all_contrataciones(status="Adjud")) == 1

    def test_inyeccion_clasica_es_dato_no_sql(self, bd):
        assert bd.get_all_contrataciones(status="x' OR '1'='1") == []
        assert len(bd.get_all_contrataciones()) == 3  # la tabla sigue intacta

    def test_reporte_escapa_comodines(self, bd):
        # "%%" como comodin traeria todo; como literal no aparece en ninguna palabra clave.
        assert bd.get_contrataciones_para_reporte(["%%"], "2025-01-01", "2025-12-31") == []
        assert len(bd.get_contrataciones_para_reporte(["luminarias"], "2025-01-01", "2025-12-31")) == 1

    def test_reporte_rechaza_demasiadas_palabras(self, bd):
        with pytest.raises(ValueError):
            bd.get_contrataciones_para_reporte(["p"] * 11, "2025-01-01", "2025-12-31")


class TestUpdateListaBlanca:
    def test_columna_valida(self, bd):
        fila = bd.get_all_contrataciones()[0]
        assert bd.update_contratacion(fila["id"], {"estado": "Finalizada"})

    def test_columna_arbitraria_se_rechaza(self, bd):
        fila = bd.get_all_contrataciones()[0]
        with pytest.raises(ValueError):
            bd.update_contratacion(fila["id"], {"estado = 'x', codigo": "y"})
        with pytest.raises(ValueError):
            bd.update_contratacion(fila["id"], {"id": 999})


class TestParametrosApi:
    def test_estado_demasiado_largo_422(self, client):
        assert client.get("/api/todos", params={"estado": "x" * 101}).status_code == 422

    def test_palabra_clave_demasiado_larga_422(self, client):
        assert client.get("/api/todos", params={"palabra_clave": "x" * 201}).status_code == 422

    def test_longitud_maxima_valida_200(self, client):
        assert client.get("/api/todos", params={"estado": "x" * 100, "palabra_clave": "x" * 200}).status_code == 200
