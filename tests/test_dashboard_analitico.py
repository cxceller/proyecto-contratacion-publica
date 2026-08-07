"""Tests de scripts/dashboard_analitico.py: las funciones que alimentan el
Treemap de presupuesto y el Gantt de procesos del "Dashboard Analítico".
Se prueban directamente sobre DataFrames (sin pasar por la API ni por
Streamlit), enfocados en que NUNCA devuelvan None ni columnas faltantes con
datos vacíos/incompletos -- justo el escenario que rompería la vista
(`resumen.empty`, `datos["etiqueta"]`, etc. en app_ui.py) si el resultado
fuera None."""
import pandas as pd
import pytest

from scripts.dashboard_analitico import (
    COLUMNAS_GANTT_PROCESOS,
    COLUMNAS_TREEMAP_PRESUPUESTO,
    construir_datos_gantt_procesos,
    construir_datos_treemap_presupuesto,
)

HOY = pd.Timestamp("2026-08-06")


def _df_registros() -> pd.DataFrame:
    """DataFrame como el que produce preparar_dataframe() en app_ui.py."""
    return pd.DataFrame(
        [
            {
                "id": 1,
                "codigo": "SIE-001",
                "entidad_contratante": "Municipalidad de Guayaquil",
                "objeto_proceso": "Adquisición de luminarias LED para el parque central",
                "estado": "Adjudicada",
                "tipo_compra": "Adquisición",
                "presupuesto_referencial": 15000.0,
                "fecha_publicacion": "2026-06-01",
            },
            {
                "id": 2,
                "codigo": "SIE-002",
                "entidad_contratante": "Municipalidad de Guayaquil",
                "objeto_proceso": "Contratación de mantenimiento vial",
                "estado": "Ejecución de",
                "tipo_compra": "Contratación",
                "presupuesto_referencial": 8000.0,
                "fecha_publicacion": "2026-07-15",
            },
            {
                "id": 3,
                "codigo": "SIE-003",
                "entidad_contratante": "Otra Entidad",
                "objeto_proceso": "Construcción de aceras",
                "estado": "Adjudicada",
                "tipo_compra": "Construcción",
                "presupuesto_referencial": 0.0,
                "fecha_publicacion": None,
            },
        ]
    )


class TestConstruirDatosTreemapPresupuesto:
    def test_dataframe_vacio_devuelve_dataframe_vacio_con_columnas(self):
        resultado = construir_datos_treemap_presupuesto(pd.DataFrame())
        assert resultado is not None
        assert resultado.empty
        assert list(resultado.columns) == COLUMNAS_TREEMAP_PRESUPUESTO

    def test_none_devuelve_dataframe_vacio_con_columnas(self):
        resultado = construir_datos_treemap_presupuesto(None)
        assert resultado is not None
        assert resultado.empty
        assert list(resultado.columns) == COLUMNAS_TREEMAP_PRESUPUESTO

    def test_columnas_faltantes_devuelve_dataframe_vacio(self):
        resultado = construir_datos_treemap_presupuesto(pd.DataFrame({"otra_columna": [1, 2]}))
        assert resultado is not None
        assert resultado.empty
        assert list(resultado.columns) == COLUMNAS_TREEMAP_PRESUPUESTO

    def test_agrupa_por_tipo_compra_y_estado_sumando_presupuesto(self):
        resultado = construir_datos_treemap_presupuesto(_df_registros())
        assert resultado is not None
        assert not resultado.empty
        fila = resultado[resultado["tipo_compra"] == "Adquisición"].iloc[0]
        assert fila["presupuesto_referencial"] == 15000.0
        assert fila["procesos"] == 1

    def test_excluye_filas_con_presupuesto_cero_o_nulo(self):
        resultado = construir_datos_treemap_presupuesto(_df_registros())
        # SIE-003 tiene presupuesto 0.0: no debe generar un rectangulo de valor 0.
        assert not (resultado["presupuesto_referencial"] <= 0).any()

    def test_presupuesto_no_numerico_no_rompe_y_se_trata_como_cero(self):
        df = _df_registros()
        df["presupuesto_referencial"] = df["presupuesto_referencial"].astype(object)
        df.loc[0, "presupuesto_referencial"] = "no-es-un-numero"
        resultado = construir_datos_treemap_presupuesto(df)
        assert resultado is not None  # no debe lanzar excepcion


class TestConstruirDatosGanttProcesos:
    def test_dataframe_vacio_devuelve_dataframe_vacio_con_columnas(self):
        resultado = construir_datos_gantt_procesos(pd.DataFrame())
        assert resultado is not None
        assert resultado.empty
        assert list(resultado.columns) == COLUMNAS_GANTT_PROCESOS

    def test_none_devuelve_dataframe_vacio_con_columnas(self):
        resultado = construir_datos_gantt_procesos(None)
        assert resultado is not None
        assert resultado.empty
        assert list(resultado.columns) == COLUMNAS_GANTT_PROCESOS

    def test_sin_columna_fecha_publicacion_devuelve_dataframe_vacio(self):
        resultado = construir_datos_gantt_procesos(pd.DataFrame({"estado": ["Adjudicada"]}))
        assert resultado is not None
        assert resultado.empty
        assert list(resultado.columns) == COLUMNAS_GANTT_PROCESOS

    def test_filas_sin_fecha_publicacion_valida_se_excluyen(self):
        resultado = construir_datos_gantt_procesos(_df_registros(), hoy=HOY)
        assert resultado is not None
        assert "SIE-003" not in resultado["codigo"].tolist()
        assert len(resultado) == 2

    def test_barras_van_desde_publicacion_hasta_hoy(self):
        resultado = construir_datos_gantt_procesos(_df_registros(), hoy=HOY)
        fila = resultado[resultado["codigo"] == "SIE-001"].iloc[0]
        assert fila["inicio"] == pd.Timestamp("2026-06-01")
        assert fila["fin"] == HOY
        assert fila["dias_transcurridos"] == (HOY - pd.Timestamp("2026-06-01")).days

    def test_etiqueta_combina_codigo_y_objeto_proceso(self):
        resultado = construir_datos_gantt_procesos(_df_registros(), hoy=HOY)
        fila = resultado[resultado["codigo"] == "SIE-002"].iloc[0]
        assert fila["etiqueta"].startswith("SIE-002")
        assert "mantenimiento vial" in fila["etiqueta"]

    def test_respeta_el_limite_de_filas(self):
        registros = [
            {
                "id": i,
                "codigo": f"SIE-{i:03d}",
                "entidad_contratante": "Municipalidad de Guayaquil",
                "objeto_proceso": "Proceso de prueba",
                "estado": "Adjudicada",
                "fecha_publicacion": f"2026-0{(i % 6) + 1}-01",
            }
            for i in range(1, 11)
        ]
        resultado = construir_datos_gantt_procesos(pd.DataFrame(registros), hoy=HOY, limite=3)
        assert len(resultado) == 3

    def test_columna_faltante_estado_o_entidad_no_rompe(self):
        df = pd.DataFrame(
            [{"codigo": "SIE-999", "objeto_proceso": "Proceso sin estado", "fecha_publicacion": "2026-01-01"}]
        )
        resultado = construir_datos_gantt_procesos(df, hoy=HOY)
        assert resultado is not None
        assert not resultado.empty
        assert resultado.iloc[0]["estado"] == ""
        assert resultado.iloc[0]["entidad_contratante"] == ""
