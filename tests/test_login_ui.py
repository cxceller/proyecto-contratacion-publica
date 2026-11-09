"""Pantalla de login (ui/autenticacion.py::requerir_login) con AppTest: el boton de envio se dibuja SIEMPRE,
el login correcto entra, el incorrecto muestra un error generico y la falta de configuracion no lanza excepciones."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import login
from ui import autenticacion

APP = str(Path(__file__).with_name("_app_login.py"))
CLAVE = "clave-de-prueba-larga"


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIN_STATE_PATH", str(tmp_path / "login.sqlite3"))
    monkeypatch.setenv("APP_USUARIO", "tester")
    monkeypatch.setenv("APP_CLAVE_HASH", login.hash_clave(CLAVE))


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30).run()


def _enviar(at: AppTest, usuario: str, clave: str) -> AppTest:
    at.text_input[0].set_value(usuario)
    at.text_input[1].set_value(clave)
    return at.button[0].click().run()


def _textos(elementos) -> str:
    return " ".join(e.value for e in elementos)


def test_la_pantalla_tiene_boton_de_envio_y_ninguna_excepcion():
    at = _app()
    assert not at.exception
    assert [b.label for b in at.button] == ["Ingresar"]
    assert len(at.text_input) == 2 and at.text_input[1].label == "Clave"
    assert at.text_input[1].proto.type == 1  # TextInput.Type.PASSWORD
    assert not at.button[0].disabled


def test_login_correcto_entra():
    at = _enviar(_app(), "tester", CLAVE)
    assert not at.exception
    assert "ENTRO" in _textos(at.markdown)


def test_login_incorrecto_muestra_error_generico_y_no_entra():
    at = _enviar(_app(), "tester", "clave-equivocada")
    assert not at.exception
    assert "ENTRO" not in _textos(at.markdown)
    assert "Usuario o clave incorrectos." in _textos(at.error)


def test_usuario_incorrecto_da_el_mismo_error_generico():
    at = _enviar(_app(), "otro", CLAVE)
    assert "Usuario o clave incorrectos." in _textos(at.error)


def test_entradas_absurdamente_largas_se_rechazan_sin_hashear(monkeypatch):
    def _no_debe_llamarse(*a, **k):
        raise AssertionError("no se debe hashear una entrada gigante")

    monkeypatch.setattr(login, "autenticar", _no_debe_llamarse)
    at = _enviar(_app(), "tester", "x" * 5000)
    assert not at.exception and "Usuario o clave incorrectos." in _textos(at.error)


def test_sin_hash_configurado_muestra_acceso_no_configurado_sin_excepcion(monkeypatch):
    monkeypatch.delenv("APP_CLAVE_HASH")
    at = _app()
    assert not at.exception
    assert "Acceso no configurado" in _textos(at.error)
    assert [b.label for b in at.button] == ["Ingresar"] and at.button[0].disabled
    assert "ENTRO" not in _textos(at.markdown)


def test_sin_usuario_configurado_tampoco_lanza(monkeypatch):
    monkeypatch.delenv("APP_USUARIO")
    at = _app()
    assert not at.exception and "Acceso no configurado" in _textos(at.error)


def test_si_falla_la_consulta_de_bloqueo_el_formulario_se_dibuja_igual(monkeypatch):
    def _roto():
        raise RuntimeError("la BD de intentos esta rota /ruta/interna")

    monkeypatch.setattr(login, "segundos_de_bloqueo", _roto)
    at = _app()
    assert not at.exception
    assert [b.label for b in at.button] == ["Ingresar"]
    assert at.button[0].disabled  # fail-closed: sin poder consultar el bloqueo, no se deja intentar
    assert "ruta/interna" not in _textos(at.error)


def test_si_falla_la_configuracion_el_formulario_se_dibuja_igual(monkeypatch):
    def _roto():
        raise RuntimeError("fallo leyendo el hash")

    monkeypatch.setattr(login, "acceso_configurado", _roto)
    at = _app()
    assert not at.exception and [b.label for b in at.button] == ["Ingresar"]


def test_si_falla_autenticar_se_muestra_un_mensaje_generico(monkeypatch):
    def _roto(*a, **k):
        raise RuntimeError("detalle interno con /ruta/secreta")

    monkeypatch.setattr(login, "autenticar", _roto)
    at = _enviar(_app(), "tester", CLAVE)
    assert not at.exception
    assert autenticacion.MENSAJE_ERROR_GENERICO in _textos(at.error)
    assert "secreta" not in _textos(at.error) and "ENTRO" not in _textos(at.markdown)


def test_bloqueo_tras_cinco_fallos_deshabilita_el_boton():
    at = _app()
    for _ in range(5):
        at = _enviar(at, "tester", "mala")
    at = _app()
    assert at.button[0].disabled and "Demasiados intentos" in _textos(at.error)


class TestAnchoCompleto:
    def test_usa_width_si_el_widget_lo_soporta(self):
        def widget(label, *, width="content"):
            pass

        assert autenticacion._kwargs_ancho_completo(widget) == {"width": "stretch"}

    def test_usa_use_container_width_en_versiones_antiguas(self):
        def widget(label, *, use_container_width=False):
            pass

        assert autenticacion._kwargs_ancho_completo(widget) == {"use_container_width": True}
