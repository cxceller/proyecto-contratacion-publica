"""Tests del reset completo de la Zona de peligro (POST /api/reset-completo,
ver src/reset.py): a diferencia de DELETE /api/todos (que solo vacia
`contrataciones`, probado en tests/test_todos.py), esto ademas respalda y
borra los .docx generados por Reportes (salidas/reportes/) y, opcionalmente,
capturas/.

`directorios_reset` redirige las constantes de directorio de src/reset.py
a subcarpetas de `tmp_path` -- sin esto, los tests tocarian las carpetas
reales del repo (capturas/, salidas/, respaldos/)."""
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.reportes_generator import generar_reporte
from src import database, reset


@pytest.fixture()
def directorios_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reset, "DIRECTORIO_CAPTURAS", tmp_path / "capturas")
    monkeypatch.setattr(reset, "DIRECTORIO_SALIDAS_REPORTES", tmp_path / "salidas" / "reportes")
    monkeypatch.setattr(reset, "DIRECTORIO_SALIDAS_CAPTURAS", tmp_path / "salidas" / "capturas")
    monkeypatch.setattr(reset, "DIRECTORIO_RESPALDOS", tmp_path / "respaldos")
    return tmp_path


def _insertar_procesos(cantidad: int, prefijo: str = "PROC") -> None:
    conn = database.get_connection()
    try:
        for i in range(cantidad):
            conn.execute(
                "INSERT INTO contrataciones "
                "(codigo, entidad_contratante, objeto_proceso, estado, fecha_publicacion, palabra_clave) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"{prefijo}-{i:03d}", "GAD Municipal de Quito", f"Objeto de prueba {i}", "Adjudicada", "2026-03-15", "prueba"),
            )
        conn.commit()
    finally:
        conn.close()


class TestResetCompletoExitoso:
    def test_criterio_de_aceptacion_38_procesos_y_reporte(self, client, directorios_reset):
        """Importo 38 procesos -> genero reporte -> reset -> Dashboard/
        Procesos/Reportes en 0 -> importo otra busqueda -> solo aparecen
        los procesos nuevos."""
        _insertar_procesos(38, prefijo="LOTE-VIEJO")

        registros = database.get_all_contrataciones()
        assert len(registros) == 38

        reset.DIRECTORIO_SALIDAS_REPORTES.mkdir(parents=True, exist_ok=True)
        ruta_reporte = reset.DIRECTORIO_SALIDAS_REPORTES / "reporte_prueba.docx"
        generar_reporte(
            df=pd.DataFrame(registros),
            palabras_clave=["prueba"],
            fecha_inicio_global=date(2026, 1, 1),
            fecha_fin_global=date(2026, 12, 31),
            ruta_salida=ruta_reporte,
            capturas_dir=reset.DIRECTORIO_CAPTURAS,
        )
        assert ruta_reporte.exists()

        response = client.post("/api/reset-completo", json={})
        assert response.status_code == 200
        resumen = response.json()
        assert resumen["procesos_eliminados"] == 38
        assert resumen["reportes_eliminados"] == 1
        assert resumen["capturas_eliminadas"] == 0

        # Dashboard/Procesos en 0.
        assert database.get_all_contrataciones() == []
        # Reportes en 0: no queda ningun .docx generado (Reporte_SERCOP.docx
        # se regenera desde cero en la proxima generacion, no hay archivo
        # fijo que "limpiar").
        assert list(reset.DIRECTORIO_SALIDAS_REPORTES.glob("*.docx")) == []

        # Importo otra busqueda: solo deben verse los procesos nuevos, sin
        # rastro del lote borrado (ni ids ni codigos viejos).
        _insertar_procesos(5, prefijo="LOTE-NUEVO")
        registros_nuevos = database.get_all_contrataciones()
        assert len(registros_nuevos) == 5
        assert all(r["codigo"].startswith("LOTE-NUEVO") for r in registros_nuevos)

    def test_respalda_la_base_de_datos_antes_de_borrar(self, client, directorios_reset):
        _insertar_procesos(3)

        response = client.post("/api/reset-completo", json={})
        assert response.status_code == 200
        respaldo_dir = reset.DIRECTORIO_RESPALDOS / Path(response.json()["respaldo_dir"]).name

        respaldo_db = respaldo_dir / "contrataciones.db"
        assert respaldo_db.exists()
        conn = sqlite3.connect(str(respaldo_db))
        try:
            (cantidad,) = conn.execute("SELECT COUNT(*) FROM contrataciones").fetchone()
        finally:
            conn.close()
        assert cantidad == 3  # el respaldo tiene los datos DE ANTES de borrar

    def test_no_expone_la_ruta_absoluta_del_respaldo(self, client, directorios_reset):
        response = client.post("/api/reset-completo", json={})
        assert response.status_code == 200
        assert not Path(response.json()["respaldo_dir"]).is_absolute()

    def test_respalda_los_docx_de_reportes(self, client, directorios_reset):
        reset.DIRECTORIO_SALIDAS_REPORTES.mkdir(parents=True, exist_ok=True)
        (reset.DIRECTORIO_SALIDAS_REPORTES / "reporte_x.docx").write_bytes(b"contenido")

        response = client.post("/api/reset-completo", json={})
        assert response.status_code == 200
        respaldo_dir = reset.DIRECTORIO_RESPALDOS / Path(response.json()["respaldo_dir"]).name

        assert (respaldo_dir / "reportes" / "reporte_x.docx").exists()

    def test_borradores_especificaciones_tecnicas_sobreviven(self, client, directorios_reset):
        """borradores_contratacion no es dato derivado de la importacion
        (son formularios que el usuario redacta a mano) -- el reset no
        debe tocarlo."""
        borrador_id = database.insert_borrador("Contratación de prueba", '{"campo": "valor"}')
        _insertar_procesos(2)

        response = client.post("/api/reset-completo", json={})
        assert response.status_code == 200

        borradores = database.get_all_borradores()
        assert any(b["id"] == borrador_id for b in borradores)


class TestResetCompletoCapturas:
    def test_borrar_capturas_false_por_defecto_no_toca_la_carpeta(self, client, directorios_reset):
        reset.DIRECTORIO_CAPTURAS.mkdir(parents=True, exist_ok=True)
        (reset.DIRECTORIO_CAPTURAS / "captura1.png").write_bytes(b"png")

        response = client.post("/api/reset-completo", json={})
        assert response.status_code == 200
        assert response.json()["capturas_eliminadas"] == 0
        assert (reset.DIRECTORIO_CAPTURAS / "captura1.png").exists()

    def test_borrar_capturas_true_vacia_la_carpeta(self, client, directorios_reset):
        reset.DIRECTORIO_CAPTURAS.mkdir(parents=True, exist_ok=True)
        (reset.DIRECTORIO_CAPTURAS / "captura1.png").write_bytes(b"png")
        (reset.DIRECTORIO_CAPTURAS / "captura2.png").write_bytes(b"png")

        response = client.post("/api/reset-completo", json={"borrar_capturas": True})
        assert response.status_code == 200
        assert response.json()["capturas_eliminadas"] == 2
        assert list(reset.DIRECTORIO_CAPTURAS.glob("*.png")) == []


class TestResetCompletoArchivoBloqueado:
    def test_docx_bloqueado_devuelve_423_y_no_toca_la_bd(self, client, directorios_reset, monkeypatch):
        _insertar_procesos(1)

        reset.DIRECTORIO_SALIDAS_REPORTES.mkdir(parents=True, exist_ok=True)
        archivo_bloqueado = reset.DIRECTORIO_SALIDAS_REPORTES / "reporte_bloqueado.docx"
        archivo_bloqueado.write_bytes(b"contenido de prueba")

        original_unlink = Path.unlink

        def unlink_simulando_bloqueo(self, *args, **kwargs):
            if self.name == "reporte_bloqueado.docx":
                raise PermissionError("simulado: archivo abierto en Word")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink_simulando_bloqueo)

        response = client.post("/api/reset-completo", json={})

        assert response.status_code == 423
        assert "Cierra Reporte_SERCOP.docx en Word y vuelve a intentar" in response.json()["detail"]

        # La BD NO se toco: el proceso insertado antes sigue ahi.
        assert len(database.get_all_contrataciones()) == 1
