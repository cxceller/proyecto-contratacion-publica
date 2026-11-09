"""Tests del modulo de Reportes (ui/reportes.py): la consulta de datos
(src/database.py::get_contrataciones_para_reporte) y el ensamblado del
.docx (scripts/reportes_generator.py::generar_reporte), incluyendo la
division de capturas demasiado altas para una pagina
(scripts/reportes_capturas.py::dividir_imagen_si_no_cabe).

Sigue el mismo patron que tests/test_database_init.py: una base SQLite
temporal por test (monkeypatch de database.DB_PATH + database.init_db()),
sin pasar por la API HTTP -- estas funciones se llaman directo desde
ui/reportes.py, no hay un endpoint de por medio."""
import numpy as np
import pandas as pd
import pytest
from docx import Document
from PIL import Image

from scripts.reportes_capturas import _slug_palabra_clave
from scripts.reportes_generator import OBSERVACION_TEXTO, generar_reporte
from src import database


@pytest.fixture()
def db_reportes(tmp_path, monkeypatch):
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return db_file


@pytest.fixture()
def insertar_contratacion(db_reportes):
    def _insertar(payload: dict) -> None:
        conn = database.get_connection()
        try:
            columnas = list(payload.keys())
            placeholders = ", ".join("?" for _ in columnas)
            conn.execute(
                f"INSERT INTO contrataciones ({', '.join(columnas)}) VALUES ({placeholders})",
                [payload[c] for c in columnas],
            )
            conn.commit()
        finally:
            conn.close()

    return _insertar


@pytest.fixture()
def contratacion_payload():
    return {
        "codigo": "SIE-001-2026",
        "entidad_contratante": "GAD Municipal de Quito",
        "objeto_proceso": "Adquisicion de luminarias LED de prueba",
        "estado": "Adjudicada",
        "provincia_canton": "Pichincha / Quito",
        "presupuesto_referencial": 15000.50,
        "fecha_publicacion": "2026-03-15",
        # Palabra clave sin coincidencia en capturas reales, para que el
        # test no dependa de archivos existentes.
        "palabra_clave": "clave-de-prueba-inexistente",
    }


class TestGetContratacionesParaReporte:
    def test_filtra_por_palabra_clave_y_fecha(self, insertar_contratacion, contratacion_payload):
        insertar_contratacion(contratacion_payload)

        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
        )

        assert len(registros) == 1
        assert registros[0]["codigo"] == "SIE-001-2026"

    def test_filtra_por_lote_id(self, insertar_contratacion, contratacion_payload):
        insertar_contratacion({**contratacion_payload, "lote_id": "lote-A"})
        insertar_contratacion({**contratacion_payload, "codigo": "SIE-002-2026", "lote_id": "lote-B"})

        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
            lote_id="lote-A",
        )

        assert len(registros) == 1
        assert registros[0]["codigo"] == "SIE-001-2026"

    def test_busqueda_insensible_a_tildes_y_mayusculas(self, insertar_contratacion, contratacion_payload):
        """SQLite LIKE (sin extensiones ICU) solo pliega mayusculas/
        minusculas en el rango ASCII: 'REPOTENCIACIÓN' con tilde no
        coincidia con una busqueda de 'repotenciacion' sin tilde."""
        insertar_contratacion(
            {**contratacion_payload, "codigo": "SIE-003-2026", "palabra_clave": "REPOTENCIACIÓN"}
        )

        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["repotenciacion"],
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
        )

        assert len(registros) == 1

    def test_sin_resultados_devuelve_lista_vacia(self, db_reportes):
        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["palabra-que-no-existe-en-ningun-proceso"],
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
        )
        assert registros == []

    def test_sin_palabras_clave_devuelve_lista_vacia(self, db_reportes):
        registros = database.get_contrataciones_para_reporte(
            palabras_clave=[], fecha_inicio="2026-01-01", fecha_fin="2026-12-31"
        )
        assert registros == []


class TestGenerarReporte:
    def test_genera_reporte_valido(self, tmp_path, insertar_contratacion, contratacion_payload):
        insertar_contratacion(contratacion_payload)
        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
        )

        ruta_salida = tmp_path / "reporte.docx"
        generar_reporte(
            df=pd.DataFrame(registros),
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio_global="2026-01-01",
            fecha_fin_global="2026-12-31",
            ruta_salida=ruta_salida,
            capturas_dir=tmp_path / "capturas_vacias",
        )

        assert ruta_salida.exists()
        documento = Document(str(ruta_salida))
        texto_completo = "\n".join(p.text for p in documento.paragraphs)
        assert "clave-de-prueba-inexistente" in texto_completo
        assert "EXISTEN 1 PROCESOS" in texto_completo
        assert len(documento.tables) == 1
        assert len(documento.tables[0].rows) == 2  # encabezado + 1 fila de datos


class TestDividirCapturaAltaEntrePaginas:
    def test_ninguna_imagen_supera_el_alto_util_de_pagina(self, tmp_path, insertar_contratacion, contratacion_payload):
        """Antes de dividir las capturas demasiado altas (ver
        scripts/reportes_capturas.py::dividir_imagen_si_no_cabe), una
        captura insertada a Inches(6) de ancho que renderizara mas de ~9"
        de alto (el alto util de una pagina carta con margenes de 1")
        quedaba recortada por Word sin ningun aviso, perdiendo filas de
        la tabla."""
        capturas_dir = tmp_path / "capturas"
        capturas_dir.mkdir()

        # Captura sintetica MUY alta (800x9000 px -> a 6" de ancho
        # renderizaria a mas de 67", muy por encima de una pagina) armada
        # con franjas alternadas oscuras/claras (90px de "fila con texto"
        # + 10px de "fila en blanco" repetidas) para que existan puntos de
        # corte limpios que _buscar_mejor_corte pueda encontrar.
        ancho_px, alto_px = 800, 9000
        franja = np.concatenate(
            [np.full((90, ancho_px), 40, dtype=np.uint8), np.full((10, ancho_px), 255, dtype=np.uint8)]
        )
        datos_imagen = np.tile(franja, (alto_px // 100, 1))
        slug = _slug_palabra_clave("clave-de-prueba-inexistente")
        Image.fromarray(datos_imagen).save(capturas_dir / f"{slug}_2026-03-15T10-00-00_pag_1.png")

        insertar_contratacion(contratacion_payload)
        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio="2026-01-01",
            fecha_fin="2026-12-31",
        )

        ruta_salida = tmp_path / "reporte.docx"
        directorio_salidas_capturas = tmp_path / "salidas_capturas"
        generar_reporte(
            df=pd.DataFrame(registros),
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio_global="2026-01-01",
            fecha_fin_global="2026-12-31",
            ruta_salida=ruta_salida,
            capturas_dir=capturas_dir,
            directorio_salidas_capturas=directorio_salidas_capturas,
        )

        documento = Document(str(ruta_salida))
        seccion = documento.sections[0]
        alto_util = seccion.page_height - seccion.top_margin - seccion.bottom_margin

        imagenes = list(documento.inline_shapes)
        assert len(imagenes) > 1, "la captura sintetica deberia haberse dividido en mas de una parte"
        for imagen in imagenes:
            assert imagen.height <= alto_util

        texto_completo = "\n".join(p.text for p in documento.paragraphs)
        assert f"parte 1 de {len(imagenes)}" in texto_completo
        assert f"parte {len(imagenes)} de {len(imagenes)}" in texto_completo

        # Las partes se guardan en el directorio indicado -- NUNCA en
        # capturas_dir (esa carpeta es de solo lectura, ver
        # scripts/reportes_capturas.py).
        assert list(directorio_salidas_capturas.glob("*_parte*de*.png"))
        assert not list(capturas_dir.glob("*_parte*de*.png"))


class TestObservacionesConObjetoCompleto:
    def test_todas_las_filas_tienen_observacion_con_objeto_completo(self, tmp_path, insertar_contratacion):
        """TODAS las filas deben llevar OBSERVACION_TEXTO + el objeto del
        proceso completo (sin recortar), en mayusculas y sin espacios
        dobles ni saltos de linea -- incluso una fila cuyo objeto ya
        menciona la palabra clave buscada (antes quedaba sin observacion;
        ahora se llena igual, sin excepciones)."""
        objeto_con_palabra_clave = "Adquisicion de luminarias LED para el cantón"
        objeto_con_espacios_raros = "Repotenciacion  del \n sistema  electrico municipal"

        insertar_contratacion(
            {
                "codigo": "SIE-010-2026",
                "entidad_contratante": "GAD Municipal de Quito",
                "objeto_proceso": objeto_con_palabra_clave,
                "estado": "Adjudicada",
                "provincia_canton": "Pichincha / Quito",
                "presupuesto_referencial": 1000,
                "fecha_publicacion": "2026-03-15",
                "palabra_clave": "luminarias",
            }
        )
        insertar_contratacion(
            {
                "codigo": "SIE-011-2026",
                "entidad_contratante": "GAD Municipal de Quito",
                "objeto_proceso": objeto_con_espacios_raros,
                "estado": "Desierta",
                "provincia_canton": "Pichincha / Quito",
                "presupuesto_referencial": 2000,
                "fecha_publicacion": "2026-04-10",
                "palabra_clave": "luminarias",
            }
        )

        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["luminarias"], fecha_inicio="2026-01-01", fecha_fin="2026-12-31"
        )
        assert len(registros) == 2

        ruta_salida = tmp_path / "reporte.docx"
        generar_reporte(
            df=pd.DataFrame(registros),
            palabras_clave=["luminarias"],
            fecha_inicio_global="2026-01-01",
            fecha_fin_global="2026-12-31",
            ruta_salida=ruta_salida,
            capturas_dir=tmp_path / "capturas_vacias",
        )

        documento = Document(str(ruta_salida))
        tabla = documento.tables[0]
        filas_datos = tabla.rows[1:]
        assert len(filas_datos) == 2

        resto_normal_esperado = OBSERVACION_TEXTO[len("NO APLICA"):]
        esperado_por_fila = {
            "SIE-010-2026": f"{resto_normal_esperado}ADQUISICION DE LUMINARIAS LED PARA EL CANTÓN",
            "SIE-011-2026": f"{resto_normal_esperado}REPOTENCIACION DEL SISTEMA ELECTRICO MUNICIPAL",
        }
        for fila in filas_datos:
            codigo = fila.cells[1].text
            runs = fila.cells[-1].paragraphs[0].runs

            # Exactamente dos runs: "NO APLICA" en negrita, el resto (texto
            # fijo + objeto del proceso) en texto normal -- no toda la
            # celda como un unico run.
            assert len(runs) == 2
            assert runs[0].text == "NO APLICA"
            assert runs[0].font.bold is True
            assert runs[1].text == esperado_por_fila[codigo]
            assert runs[1].font.bold is False

            observacion_completa = runs[0].text + runs[1].text
            assert "\n" not in observacion_completa
            assert "  " not in observacion_completa

    def test_checkbox_destildado_deja_observaciones_vacias(self, tmp_path, insertar_contratacion, contratacion_payload):
        insertar_contratacion(contratacion_payload)
        registros = database.get_contrataciones_para_reporte(
            palabras_clave=["clave-de-prueba-inexistente"], fecha_inicio="2026-01-01", fecha_fin="2026-12-31"
        )

        ruta_salida = tmp_path / "reporte.docx"
        generar_reporte(
            df=pd.DataFrame(registros),
            palabras_clave=["clave-de-prueba-inexistente"],
            fecha_inicio_global="2026-01-01",
            fecha_fin_global="2026-12-31",
            ruta_salida=ruta_salida,
            capturas_dir=tmp_path / "capturas_vacias",
            llenar_observaciones=False,
        )

        documento = Document(str(ruta_salida))
        fila_datos = documento.tables[0].rows[1]
        assert fila_datos.cells[-1].text == ""
