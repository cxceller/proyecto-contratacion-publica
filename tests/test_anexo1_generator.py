"""Tests de generar_anexo1() (scripts/anexo1_generator.py): arma el
.docx del Anexo 1 - Especificaciones Tecnicas directamente (sin pasar por
la API ni por Streamlit), inspeccionando el documento resultante con
python-docx."""
from pathlib import Path

import pytest
from docx import Document

from scripts.anexo1_generator import generar_anexo1


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


class TestGenerarAnexo1:
    def test_genera_documento_con_items_bien_y_servicio(self, tmp_path, item_bien, item_servicio):
        datos = {
            "objeto_contratacion": "Adquisicion y mantenimiento de luminarias LED",
            "items": [item_bien, item_servicio],
        }

        ruta = generar_anexo1(datos, tmp_path / "anexo1.docx")

        assert ruta.exists()
        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "Adquisicion y mantenimiento de luminarias LED" in texto
        assert "Luminarias LED" in texto
        assert "Mantenimiento de luminarias" in texto

    def test_item_bien_incluye_tabla_de_parametros(self, tmp_path, item_bien):
        ruta = generar_anexo1({"objeto_contratacion": "Prueba", "items": [item_bien]}, tmp_path / "anexo1.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "MODELO DE EJEMPLO" in texto
        assert "Cuerpo de aluminio" in texto
        assert "Potencia" in texto and "100W" in texto
        assert "Voltaje" in texto and "110V" in texto

    def test_item_servicio_incluye_bloques_de_texto_libre(self, tmp_path, item_servicio):
        ruta = generar_anexo1(
            {"objeto_contratacion": "Prueba", "items": [item_servicio]}, tmp_path / "anexo1.docx"
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
        ruta = generar_anexo1({"objeto_contratacion": "Sin items"}, tmp_path / "anexo1.docx")

        assert ruta.exists()
        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "CONDICIONES LEGALES Y ADMINISTRATIVAS" in texto
        assert "FIRMAS DE RESPONSABILIDAD" in texto

    def test_campos_legales_vacios_muestran_placeholder_llenar(self, tmp_path):
        ruta = generar_anexo1({}, tmp_path / "anexo1.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "LLENAR" in texto

    def test_patrimonio_si_incluye_tablas_de_rangos(self, tmp_path):
        datos = {"objeto_contratacion": "Prueba", "patrimonio_aplica": "Sí"}
        ruta = generar_anexo1(datos, tmp_path / "anexo1.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "Bienes y/o Servicios" in texto
        assert "Obras" in texto

    def test_patrimonio_no_omite_tablas_de_rangos(self, tmp_path):
        datos = {"objeto_contratacion": "Prueba", "patrimonio_aplica": "No"}
        ruta = generar_anexo1(datos, tmp_path / "anexo1.docx")

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
        ruta = generar_anexo1(datos, tmp_path / "anexo1.docx")

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
        ruta = generar_anexo1(datos, tmp_path / "anexo1.docx")

        documento = Document(str(ruta))
        texto = _texto_completo(documento)
        assert "44101500" in texto and "Lamparas LED" in texto
        assert "85111600" in texto and "Servicios de mantenimiento" in texto

    def test_ruta_salida_acepta_string(self, tmp_path):
        ruta_str = str(tmp_path / "anexo1_como_string.docx")
        ruta = generar_anexo1({"objeto_contratacion": "Prueba"}, ruta_str)

        assert isinstance(ruta, Path)
        assert ruta.exists()
