"""Tests de src/login.py: hash argon2id, fail-closed, bloqueo temporal
creciente persistido (1/5/15 min, nunca permanente)."""
import pytest

from src import login

CLAVE = "una-clave-larga-de-prueba"


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIN_STATE_PATH", str(tmp_path / "login.sqlite3"))
    monkeypatch.setenv("APP_USUARIO", "admin_prueba")
    monkeypatch.setenv("APP_CLAVE_HASH", login.hash_clave(CLAVE))


class TestHash:
    def test_es_argon2id(self):
        assert login.hash_clave(CLAVE).startswith("$argon2id$")

    def test_verifica_correcta_e_incorrecta(self):
        h = login.hash_clave(CLAVE)
        assert login.verificar_clave(CLAVE, h)
        assert not login.verificar_clave("otra", h)

    def test_hash_invalido_o_vacio_no_lanza(self):
        assert not login.verificar_clave(CLAVE, "no-es-un-hash")
        assert not login.verificar_clave(CLAVE, None)


class TestAutenticar:
    def test_ok(self):
        assert login.autenticar("admin_prueba", CLAVE, ahora=1000) == login.OK

    def test_usuario_o_clave_incorrectos(self):
        assert login.autenticar("otro", CLAVE, ahora=1000) == login.INVALIDA
        assert login.autenticar("admin_prueba", "mala", ahora=1000) == login.INVALIDA

    def test_fail_closed_sin_configuracion(self, monkeypatch):
        monkeypatch.delenv("APP_CLAVE_HASH")
        assert login.autenticar("admin_prueba", CLAVE) == login.NO_CONFIGURADO
        monkeypatch.setenv("APP_CLAVE_HASH", login.hash_clave(CLAVE))
        monkeypatch.delenv("APP_USUARIO")
        assert login.autenticar("admin_prueba", CLAVE) == login.NO_CONFIGURADO

    def test_clave_en_texto_plano_legacy_no_sirve(self, monkeypatch):
        monkeypatch.setenv("APP_CLAVE_HASH", CLAVE)  # alguien pego la clave en vez del hash
        assert login.autenticar("admin_prueba", CLAVE) == login.INVALIDA


class TestBloqueo:
    def _fallar(self, veces, ahora):
        for _ in range(veces):
            login.autenticar("admin_prueba", "mala", ahora=ahora)

    def test_no_bloquea_antes_de_5_fallos(self):
        self._fallar(4, 1000)
        assert login.segundos_de_bloqueo(1000) == 0
        assert login.autenticar("admin_prueba", CLAVE, ahora=1000) == login.OK

    def test_bloquea_1_minuto_al_quinto_fallo_y_rechaza_aun_con_clave_correcta(self):
        self._fallar(5, 1000)
        assert login.segundos_de_bloqueo(1000) == 60
        assert login.autenticar("admin_prueba", CLAVE, ahora=1030) == login.BLOQUEADO

    def test_se_desbloquea_solo_al_pasar_el_tiempo(self):
        self._fallar(5, 1000)
        assert login.segundos_de_bloqueo(1061) == 0
        assert login.autenticar("admin_prueba", CLAVE, ahora=1061) == login.OK

    def test_bloqueo_creciente_1_5_15_y_nunca_permanente(self):
        self._fallar(5, 1000)
        assert login.segundos_de_bloqueo(1000) == 60
        self._fallar(5, 2000)
        assert login.segundos_de_bloqueo(2000) == 300
        self._fallar(5, 4000)
        assert login.segundos_de_bloqueo(4000) == 900
        self._fallar(5, 6000)
        assert login.segundos_de_bloqueo(6000) == 900  # tope: sigue siendo temporal
        assert login.segundos_de_bloqueo(6901) == 0

    def test_exito_reinicia_contadores_y_nivel(self):
        self._fallar(5, 1000)
        assert login.autenticar("admin_prueba", CLAVE, ahora=1100) == login.OK
        self._fallar(5, 2000)
        assert login.segundos_de_bloqueo(2000) == 60  # volvio al primer nivel

    def test_persiste_fuera_de_la_sesion(self):
        self._fallar(5, 1000)
        # "otra sesion" = nueva conexion al mismo archivo
        assert login.segundos_de_bloqueo(1010) > 0


class TestReautenticar:
    def test_reautenticar_usa_el_mismo_bloqueo(self):
        assert login.reautenticar(CLAVE, ahora=1000) == login.OK
        for _ in range(5):
            login.reautenticar("mala", ahora=1000)
        assert login.reautenticar(CLAVE, ahora=1010) == login.BLOQUEADO
