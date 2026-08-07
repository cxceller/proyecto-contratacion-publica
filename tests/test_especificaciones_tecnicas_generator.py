"""Tests de generar_especificaciones_tecnicas() (scripts/especificaciones_tecnicas_generator.py):
arma el .docx de Especificaciones Tecnicas directamente (sin pasar por
la API ni por Streamlit), inspeccionando el documento resultante con
python-docx."""
import base64
import io
from pathlib import Path

import pytest
from docx import Document

from scripts.especificaciones_tecnicas_generator import _insertar_html_en_celda, generar_especificaciones_tecnicas


def _texto_de_celda(celda) -> str:
    """celda.text de python-docx no baja a tablas anidadas (como la
    subtabla de parametros dentro de la celda de especificaciones
    tecnicas de un item Bien), asi que hay que recorrerlas a mano."""
    partes = [p.text for p in celda.paragraphs]
    for tabla_anidada in celda.tables:
        for fila in tabla_anidada.rows:
            for sub_celda in fila.cells:
                partes.append(_texto_de_celda(sub_celda))
    return "\n".join(partes)


def _texto_completo(documento: Document) -> str:
    partes = [p.text for p in documento.paragraphs]
    for tabla in documento.tables:
        for fila in tabla.rows:
            for celda in fila.cells:
                partes.append(_texto_de_celda(celda))
    return "\n".join(partes)


@pytest.fixture()
def item_bien():
    return {
        "tipo": "Bien",
        "descripcion": "Luminarias LED",
        "unidad_medida": "Unidad",
        "cantidad_solicitada": "10",
        "valor_unitario": "50.00",
        "valor_total": "500.00",
        "descripcion_cpc": "Lamparas",
        "numero_cpc": "44101500",
        "subtitulo_specs": "MODELO DE EJEMPLO",
        "descripcion_material": "Cuerpo de aluminio",
        "parametros": [
            {"nombre": "Potencia", "valor": "100W"},
            {"nombre": "Voltaje", "valor": "110V"},
        ],
    }


@pytest.fixture()
def item_servicio():
    return {
        "tipo": "Servicio",
        "descripcion": "Mantenimiento de luminarias",
        "unidad_medida": "Servicio",
        "cantidad_solicitada": "1",
        "valor_unitario": "1000.00",
        "valor_total": "1000.00",
        "descripcion_cpc": "Servicios de mantenimiento",
        "numero_cpc": "85111600",
        "procedimiento": "Desmontaje y montaje segun manual del fabricante",
        "herramientas_equipo": "Escalera, multimetro",
        "normas_aplicables": "NTE INEN 2506",
        "medicion": "Por unidad instalada",
        "forma_pago": "Contra entrega",
        "obligaciones": "Entregar informe tecnico",
    }


class TestGenerarEspecificacionesTecnicas:
    def test_genera_documento_con_items_bien_y_servicio(self, tmp_path, item_bien, item_servicio):
        datos = {
            "objeto_contratacion": "Adquisicion y mantenimiento de luminarias LED",
            "items": [item_bien, item_servicio],
        }

        ruta = generar_especificaciones_tecnicas(datos, tmp_path / "especificaciones_tecnicas.docx")

        assert ruta.exists()
        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "Adquisicion y mantenimiento de luminarias LED" in texto
        assert "Luminarias LED" in texto
        assert "Mantenimiento de luminarias" in texto

    def test_item_bien_incluye_tabla_de_parametros(self, tmp_path, item_bien):
        ruta = generar_especificaciones_tecnicas({"objeto_contratacion": "Prueba", "items": [item_bien]}, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "MODELO DE EJEMPLO" in texto
        assert "Cuerpo de aluminio" in texto
        assert "Potencia" in texto and "100W" in texto
        assert "Voltaje" in texto and "110V" in texto

    def test_item_servicio_incluye_bloques_de_texto_libre(self, tmp_path, item_servicio):
        ruta = generar_especificaciones_tecnicas(
            {"objeto_contratacion": "Prueba", "items": [item_servicio]}, tmp_path / "especificaciones_tecnicas.docx"
        )

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "PROCEDIMIENTO" in texto
        assert "Desmontaje y montaje segun manual del fabricante" in texto
        assert "Escalera, multimetro" in texto
        assert "NTE INEN 2506" in texto
        assert "Por unidad instalada" in texto
        assert "Contra entrega" in texto
        assert "Entregar informe tecnico" in texto

    def test_sin_items_genera_documento_valido_solo_con_seccion_legal(self, tmp_path):
        ruta = generar_especificaciones_tecnicas({"objeto_contratacion": "Sin items"}, tmp_path / "especificaciones_tecnicas.docx")

        assert ruta.exists()
        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "REQUERIMIENTOS ADICIONALES OBLIGATORIOS" in texto
        assert "PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN" in texto
        assert "FIRMAS DE RESPONSABILIDAD" in texto

    def test_campos_legales_vacios_no_muestran_placeholder(self, tmp_path):
        ruta = generar_especificaciones_tecnicas({}, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "LLENAR" not in texto

    def test_patrimonio_si_incluye_tablas_de_rangos(self, tmp_path):
        datos = {"objeto_contratacion": "Prueba", "patrimonio_aplica": "Sí"}
        ruta = generar_especificaciones_tecnicas(datos, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "Bienes y/o Servicios" in texto
        assert "Obras" in texto

    def test_patrimonio_no_omite_tablas_de_rangos(self, tmp_path):
        datos = {"objeto_contratacion": "Prueba", "patrimonio_aplica": "No"}
        ruta = generar_especificaciones_tecnicas(datos, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "Bienes y/o Servicios" not in texto

    def test_firmas_se_incluyen_en_tabla(self, tmp_path):
        datos = {
            "objeto_contratacion": "Prueba",
            "firmas": {
                "elaborado": {"nombre": "Juan Perez", "cargo": "Analista", "firmado_por": "JP"},
                "revisado": {"nombre": "Maria Lopez", "cargo": "Supervisora", "firmado_por": "ML"},
                "aprobado": {"nombre": "Carlos Ruiz", "cargo": "Director", "firmado_por": "CR"},
            },
        }
        ruta = generar_especificaciones_tecnicas(datos, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "Juan Perez" in texto
        assert "Maria Lopez" in texto
        assert "Carlos Ruiz" in texto

    def test_requerimientos_cpc_multiples_se_listan_en_tabla(self, tmp_path):
        datos = {
            "objeto_contratacion": "Prueba",
            "requerimientos_cpc": [
                {"cpc": "44101500", "descripcion": "Lamparas LED"},
                {"cpc": "85111600", "descripcion": "Servicios de mantenimiento"},
            ],
        }
        ruta = generar_especificaciones_tecnicas(datos, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "44101500" in texto and "Lamparas LED" in texto
        assert "85111600" in texto and "Servicios de mantenimiento" in texto

    def test_ruta_salida_acepta_string(self, tmp_path):
        ruta_str = str(tmp_path / "especificaciones_tecnicas_como_string.docx")
        ruta = generar_especificaciones_tecnicas({"objeto_contratacion": "Prueba"}, ruta_str)

        assert isinstance(ruta, Path)
        assert ruta.exists()

    def test_analisis_estrategia_html_con_tabla_e_imagen(self, tmp_path):
        """Simula lo que el editor TinyMCE produce al pegar una tabla desde
        Excel con una imagen en una celda (paste_data_images=True incrusta
        la imagen como base64): debe convertirse en una tabla real del
        .docx, con la imagen incrustada, y no como texto plano."""
        from PIL import Image

        buffer_imagen = io.BytesIO()
        Image.new("RGB", (20, 10), color=(200, 30, 30)).save(buffer_imagen, format="PNG")
        imagen_b64 = base64.b64encode(buffer_imagen.getvalue()).decode()

        html_tabla = (
            "<table><tbody>"
            "<tr><td>A1</td><td>B1</td><td>C1</td></tr>"
            f'<tr><td>A2</td><td><img src="data:image/png;base64,{imagen_b64}"></td><td>C2</td></tr>'
            "<tr><td>A3</td><td>B3</td><td>C3</td></tr>"
            "</tbody></table>"
        )
        datos = {"objeto_contratacion": "Prueba", "analisis_estrategia_html": html_tabla}
        ruta = generar_especificaciones_tecnicas(datos, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        tabla_legal = documento.tables[1]

        def _buscar_tabla_anidada(celda):
            for t in celda.tables:
                filas = [[c.text.strip() for c in f.cells] for f in t.rows]
                if filas and filas[0] == ["A1", "B1", "C1"]:
                    return t
            return None

        tabla_pegada = None
        celda_con_imagen = None
        for fila in tabla_legal.rows:
            for celda in fila.cells:
                encontrada = _buscar_tabla_anidada(celda)
                if encontrada is not None:
                    tabla_pegada = encontrada
                    celda_con_imagen = celda
                    break
            if tabla_pegada:
                break

        assert tabla_pegada is not None, "la tabla pegada no se encontro en el documento"
        assert [c.text.strip() for c in tabla_pegada.rows[1].cells][::2] == ["A2", "C2"]
        assert "<pic:pic" in celda_con_imagen._tc.xml

    def test_analisis_estrategia_html_vacio_no_muestra_placeholder(self, tmp_path):
        ruta = generar_especificaciones_tecnicas({"objeto_contratacion": "Prueba"}, tmp_path / "especificaciones_tecnicas.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "LLENAR" not in texto


class TestInsertarHtmlEnCelda:
    """_insertar_html_en_celda es el punto de entrada de mas bajo nivel:
    convierte HTML (potencialmente con tablas/imagenes pegadas desde
    Excel/Word) a contenido real del .docx, con degradacion seguro a
    texto plano si htmldocx no soporta alguna estructura."""

    def _celda_vacia(self):
        return Document().add_table(rows=1, cols=1).cell(0, 0)

    def test_html_con_estructura_no_soportada_no_lanza_excepcion(self):
        """Una tabla con colspan/rowspan irregulares (numero de celdas por
        fila que no coincide con las dimensiones esperadas) es un caso
        clasico que rompe conversores html->docx simples -- no debe
        fallar la generacion del documento completo, sino degradar a
        texto plano."""
        html_irregular = (
            "<table>"
            '<tr><td colspan="3">Encabezado combinado</td></tr>'
            '<tr><td rowspan="2">A</td><td>B</td></tr>'
            "<tr><td>C</td><td>D</td><td>E</td><td>F</td></tr>"
            "</table>"
        )
        celda = self._celda_vacia()
        _insertar_html_en_celda(celda, html_irregular)  # no debe lanzar
        assert celda.paragraphs or celda.tables

    def test_html_vacio_no_agrega_placeholder(self):
        celda = self._celda_vacia()
        _insertar_html_en_celda(celda, "")
        texto = "\n".join(p.text for p in celda.paragraphs)
        assert "LLENAR" not in texto
        assert texto.strip() == ""
