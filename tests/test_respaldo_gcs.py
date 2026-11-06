"""Respaldo del reset en Cloud Storage (solo Cloud Run): se sube ANTES de
borrar, aborta si falla (fail-closed) y se puede listar/restaurar desde el
bucket. Cliente de GCS simulado en memoria: no hay red ni credenciales."""
import base64
import hashlib
import sqlite3
from pathlib import Path

import pytest

from src import database, reset, respaldo_gcs
from src.respaldo_gcs import RespaldoRemotoError
from src.restauracion import restaurar


def _md5(b: bytes) -> str:
    return base64.b64encode(hashlib.md5(b, usedforsecurity=False).digest()).decode()


class ClienteFalso:
    """Misma interfaz que ClienteGCS (subir / listar / listar_respaldos / descargar)."""

    def __init__(self, prefijo="respaldos/", falla_en_subida=False, md5_incorrecto=False, alterar_descarga=False):
        self.prefijo = prefijo
        self.objetos: dict[str, bytes] = {}
        self.falla_en_subida = falla_en_subida
        self.md5_incorrecto = md5_incorrecto
        self.alterar_descarga = alterar_descarga
        self.estado_al_subir: list[tuple[int, bool]] = []  # (filas en la BD, docx existe) en cada subida

    def subir(self, nombre, contenido):
        if self.falla_en_subida:
            raise respaldo_gcs.requests.ConnectionError("sin red")
        self.estado_al_subir.append((_filas(database.DB_PATH), (reset.DIRECTORIO_SALIDAS_REPORTES / "r1.docx").exists()))
        self.objetos[nombre] = contenido
        return "AAAA" if self.md5_incorrecto else _md5(contenido)

    def listar(self, prefijo, delimitador=None):
        items = [{"name": n, "md5Hash": _md5(c), "size": str(len(c))} for n, c in sorted(self.objetos.items()) if n.startswith(prefijo)]
        prefijos = []
        if delimitador:
            vistos = set()
            for n in self.objetos:
                if n.startswith(prefijo) and delimitador in n[len(prefijo):]:
                    vistos.add(prefijo + n[len(prefijo):].split(delimitador)[0] + delimitador)
            prefijos = sorted(vistos)
            items = [i for i in items if delimitador not in i["name"][len(prefijo):]]
        return {"items": items, "prefixes": prefijos}

    def listar_respaldos(self):
        return respaldo_gcs.ClienteGCS.listar_respaldos(self)

    def descargar(self, nombre):
        c = self.objetos[nombre]
        return c + b"x" if self.alterar_descarga else c


def _filas(ruta_db) -> int:
    c = sqlite3.connect(str(ruta_db))
    try:
        return c.execute("SELECT COUNT(*) FROM contrataciones").fetchone()[0]
    finally:
        c.close()


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "vivo.db"))
    monkeypatch.setattr(reset, "DIRECTORIO_CAPTURAS", tmp_path / "capturas")
    monkeypatch.setattr(reset, "DIRECTORIO_SALIDAS_REPORTES", tmp_path / "salidas" / "reportes")
    monkeypatch.setattr(reset, "DIRECTORIO_SALIDAS_CAPTURAS", tmp_path / "salidas" / "capturas")
    monkeypatch.setattr(reset, "DIRECTORIO_RESPALDOS", tmp_path / "respaldos")
    monkeypatch.setattr(reset, "RAIZ_PROYECTO", tmp_path)
    database.init_db()
    for i in range(4):
        database.insert_contratacion(
            {"codigo": f"G-{i}", "entidad_contratante": "E", "objeto_proceso": "o", "estado": "Desierta",
             "provincia_canton": None, "presupuesto_referencial": 1.0, "fecha_publicacion": "2025-01-01",
             "palabra_clave": "k", "url": None, "lote_id": None, "monto_adjudicado": None,
             "motivo_estado_raw": None, "explicacion_estado": None})
    (tmp_path / "salidas" / "reportes").mkdir(parents=True)
    (tmp_path / "salidas" / "reportes" / "r1.docx").write_bytes(b"docx-uno")
    return tmp_path


def _en_cloud_run(monkeypatch, cliente):
    monkeypatch.setenv("K_SERVICE", "sercop")
    monkeypatch.setattr(respaldo_gcs, "crear_cliente", lambda: cliente)


class TestResetEnCloudRun:
    def test_sube_el_respaldo_ANTES_de_borrar(self, entorno, monkeypatch):
        cliente = ClienteFalso()
        _en_cloud_run(monkeypatch, cliente)
        resumen = reset.ejecutar_reset_completo()

        assert resumen["procesos_eliminados"] == 4 and _filas(database.DB_PATH) == 0
        marca = Path(resumen["respaldo_dir"]).name
        assert resumen["respaldo_remoto"] == f"respaldos/{marca}"
        assert set(cliente.objetos) == {f"respaldos/{marca}/contrataciones.db", f"respaldos/{marca}/reportes/r1.docx"}
        assert cliente.objetos[f"respaldos/{marca}/reportes/r1.docx"] == b"docx-uno"
        # En el instante de cada subida los datos AUN existian (nada se habia borrado).
        assert cliente.estado_al_subir and all(filas == 4 and docx for filas, docx in cliente.estado_al_subir)

    def test_el_respaldo_remoto_tiene_los_datos_de_antes(self, entorno, monkeypatch, tmp_path):
        cliente = ClienteFalso()
        _en_cloud_run(monkeypatch, cliente)
        resumen = reset.ejecutar_reset_completo()
        copia = tmp_path / "bajada.db"
        copia.write_bytes(cliente.objetos[f"respaldos/{Path(resumen['respaldo_dir']).name}/contrataciones.db"])
        assert _filas(copia) == 4

    def test_si_la_subida_falla_no_se_borra_nada(self, entorno, monkeypatch):
        _en_cloud_run(monkeypatch, ClienteFalso(falla_en_subida=True))
        with pytest.raises(RespaldoRemotoError):
            reset.ejecutar_reset_completo()
        assert _filas(database.DB_PATH) == 4
        assert (entorno / "salidas" / "reportes" / "r1.docx").exists()

    def test_si_el_checksum_no_coincide_no_se_borra_nada(self, entorno, monkeypatch):
        _en_cloud_run(monkeypatch, ClienteFalso(md5_incorrecto=True))
        with pytest.raises(RespaldoRemotoError):
            reset.ejecutar_reset_completo()
        assert _filas(database.DB_PATH) == 4 and (entorno / "salidas" / "reportes" / "r1.docx").exists()

    def test_sin_bucket_configurado_aborta_y_no_borra(self, entorno, monkeypatch):
        monkeypatch.setenv("K_SERVICE", "sercop")
        monkeypatch.delenv("SERCOP_DB_BUCKET", raising=False)
        with pytest.raises(RespaldoRemotoError):
            reset.ejecutar_reset_completo()
        assert _filas(database.DB_PATH) == 4

    def test_endpoint_responde_503_generico_y_no_borra(self, client, entorno, monkeypatch):
        _en_cloud_run(monkeypatch, ClienteFalso(falla_en_subida=True))
        respuesta = client.post("/api/reset-completo", json={})
        assert respuesta.status_code == 503
        assert "no se borró nada" in respuesta.json()["detail"]
        assert "sin red" not in respuesta.text and "Connection" not in respuesta.text
        assert _filas(database.DB_PATH) == 4

    def test_endpoint_ok_incluye_respaldo_remoto(self, client, entorno, monkeypatch):
        _en_cloud_run(monkeypatch, ClienteFalso())
        cuerpo = client.post("/api/reset-completo", json={}).json()
        assert cuerpo["respaldo_remoto"].startswith("respaldos/")
        assert not Path(cuerpo["respaldo_dir"]).is_absolute()


class TestEnLocalSigueComoAntes:
    def test_no_toca_el_bucket(self, entorno, monkeypatch):
        monkeypatch.delenv("K_SERVICE", raising=False)

        def _no_debe_llamarse():
            raise AssertionError("en local no se debe crear el cliente de GCS")

        monkeypatch.setattr(respaldo_gcs, "crear_cliente", _no_debe_llamarse)
        resumen = reset.ejecutar_reset_completo()
        assert resumen["respaldo_remoto"] is None and resumen["procesos_eliminados"] == 4

    def test_directorio_de_respaldos_por_defecto(self, monkeypatch):
        monkeypatch.delenv("K_SERVICE", raising=False)
        assert reset._directorio_respaldos_por_defecto() == reset.RAIZ_PROYECTO / "respaldos"
        monkeypatch.setenv("K_SERVICE", "sercop")
        monkeypatch.delenv("RESPALDOS_DIR", raising=False)
        assert reset._directorio_respaldos_por_defecto() == Path("/tmp/respaldos")


class TestRestaurarDesdeElBucket:
    def _reset_y_cliente(self, entorno, monkeypatch, **opciones):
        cliente = ClienteFalso(**opciones)
        _en_cloud_run(monkeypatch, cliente)
        resumen = reset.ejecutar_reset_completo()
        cliente.alterar_descarga = opciones.get("alterar_descarga", False)
        return cliente, Path(resumen["respaldo_dir"]).name

    def test_lista_los_respaldos_del_bucket(self, entorno, monkeypatch):
        cliente, marca = self._reset_y_cliente(entorno, monkeypatch)
        cliente.objetos["snapshots/contrataciones.db"] = b"otro"
        cliente.objetos["respaldos/pre_restauracion_x/contrataciones.db"] = b"no es un respaldo de reset"
        assert respaldo_gcs.listar_respaldos(cliente) == [marca]

    def test_restaura_desde_gcs_y_los_datos_quedan_iguales(self, entorno, monkeypatch):
        cliente, marca = self._reset_y_cliente(entorno, monkeypatch)
        assert _filas(database.DB_PATH) == 0
        plan = restaurar(marca, confirmar=True, origen="gcs", cliente=cliente)
        assert plan["aplicado"] and plan["origen"] == "gcs" and plan["contrataciones_en_respaldo"] == 4
        assert _filas(database.DB_PATH) == 4
        assert (entorno / "salidas" / "reportes" / "r1.docx").read_bytes() == b"docx-uno"

    def test_sin_confirmar_solo_informa(self, entorno, monkeypatch):
        cliente, marca = self._reset_y_cliente(entorno, monkeypatch)
        plan = restaurar(marca, origen="gcs", cliente=cliente)
        assert not plan["aplicado"] and _filas(database.DB_PATH) == 0

    def test_descarga_alterada_se_rechaza_y_no_toca_la_bd(self, entorno, monkeypatch):
        cliente, marca = self._reset_y_cliente(entorno, monkeypatch)
        cliente.alterar_descarga = True
        with pytest.raises(RespaldoRemotoError):
            restaurar(marca, confirmar=True, origen="gcs", cliente=cliente)
        assert _filas(database.DB_PATH) == 0

    def test_respaldo_inexistente_en_el_bucket(self, entorno):
        with pytest.raises(RespaldoRemotoError):
            restaurar("20250101_000000", confirmar=True, origen="gcs", cliente=ClienteFalso())

    @pytest.mark.parametrize("nombre", ["../x", "..", "abc", "2025", "20250101_000000/../../x"])
    def test_nombres_invalidos(self, entorno, nombre):
        with pytest.raises(Exception):  # noqa: B017 -- RespaldoRemotoError o RespaldoInvalidoError
            restaurar(nombre, confirmar=True, origen="gcs", cliente=ClienteFalso())

    def test_ruta_remota_con_traversal_se_rechaza(self, entorno, tmp_path):
        cliente = ClienteFalso()
        cliente.objetos["respaldos/20250101_000000/../../fuera.txt"] = b"malo"
        with pytest.raises(RespaldoRemotoError):
            respaldo_gcs.descargar_respaldo("20250101_000000", tmp_path / "destino", cliente=cliente)
        assert not (tmp_path / "fuera.txt").exists()


class _Resp:
    def __init__(self, json_=None, content=b""):
        self._json, self.content = json_ or {}, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class TestClienteHttpReal:
    """ClienteGCS con `requests` simulado: verifica URL, parametros y cabeceras."""

    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch):
        monkeypatch.setattr(respaldo_gcs, "_obtener_token", lambda: "tok-123")

    def test_subir_usa_upload_media_con_nombre_en_params_y_token(self, monkeypatch):
        capturado = {}

        def post(url, params=None, data=None, headers=None, timeout=None):
            capturado.update(url=url, params=params, data=data, headers=headers, timeout=timeout)
            return _Resp({"md5Hash": _md5(data)})

        monkeypatch.setattr(respaldo_gcs.requests, "post", post)
        cliente = respaldo_gcs.ClienteGCS("mi-bucket")
        assert cliente.subir("respaldos/2025/x.db", b"abc") == _md5(b"abc")
        assert capturado["url"] == "https://storage.googleapis.com/upload/storage/v1/b/mi-bucket/o"
        assert capturado["params"] == {"uploadType": "media", "name": "respaldos/2025/x.db"}
        assert capturado["headers"]["Authorization"] == "Bearer tok-123" and capturado["timeout"]

    def test_listar_recorre_todas_las_paginas(self, monkeypatch):
        paginas = [
            {"prefixes": ["respaldos/20250101_000000/"], "nextPageToken": "p2"},
            {"prefixes": ["respaldos/20250202_000000/", "respaldos/otro/"]},
        ]
        pedidos = []

        def get(url, params=None, headers=None, timeout=None):
            pedidos.append(dict(params))
            return _Resp(paginas[len(pedidos) - 1])

        monkeypatch.setattr(respaldo_gcs.requests, "get", get)
        assert respaldo_gcs.ClienteGCS("mi-bucket").listar_respaldos() == ["20250101_000000", "20250202_000000"]
        assert pedidos[0] == {"prefix": "respaldos/", "delimiter": "/"} and pedidos[1]["pageToken"] == "p2"

    def test_descargar_codifica_el_nombre_del_objeto(self, monkeypatch):
        urls = []

        def get(url, params=None, headers=None, timeout=None):
            urls.append((url, params))
            return _Resp(content=b"datos")

        monkeypatch.setattr(respaldo_gcs.requests, "get", get)
        assert respaldo_gcs.ClienteGCS("mi-bucket").descargar("respaldos/2025/x.db") == b"datos"
        assert urls[0][0].endswith("/o/respaldos%2F2025%2Fx.db") and urls[0][1] == {"alt": "media"}

    @pytest.mark.parametrize("bucket", ["", "UPPER", "a/b", "x?y", "../b"])
    def test_bucket_invalido(self, bucket):
        with pytest.raises(RespaldoRemotoError):
            respaldo_gcs.ClienteGCS(bucket)

    @pytest.mark.parametrize("prefijo", ["../x", "/abs", "a b", "x" * 200])
    def test_prefijo_invalido(self, monkeypatch, prefijo):
        monkeypatch.setenv("SERCOP_RESPALDOS_PREFIX", prefijo)
        with pytest.raises(RespaldoRemotoError):
            respaldo_gcs._prefijo()

    def test_error_de_red_se_convierte_en_error_generico(self, entorno, monkeypatch, tmp_path):
        def post(*a, **k):
            raise respaldo_gcs.requests.ConnectionError("detalle interno con /ruta/secreta")

        monkeypatch.setattr(respaldo_gcs.requests, "post", post)
        carpeta = tmp_path / "r"
        carpeta.mkdir()
        (carpeta / "contrataciones.db").write_bytes(b"x")
        with pytest.raises(RespaldoRemotoError) as exc:
            respaldo_gcs.subir_respaldo(carpeta, "20250101_000000", cliente=respaldo_gcs.ClienteGCS("mi-bucket"))
        assert "secreta" not in str(exc.value)
