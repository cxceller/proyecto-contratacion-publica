"""Tests del autocompletado de "Descripcion CPC" en la pestana "Items y
Valores" del Especificaciones Técnicas (app_ui.py): al guardar, si el "Numero CPC" de una
fila cambio respecto al guardado anterior y el codigo existe en el
catalogo oficial (data/cpc_n9.csv, SERCOP), se autocompleta la
descripcion; si no cambio o el codigo no existe, se respeta lo que el
usuario haya dejado.

La identidad de "la misma fila" entre un guardado y el siguiente se
rastrea con "_fila_id" (ver _asignar_fila_ids_especificaciones_tecnicas), NO con la
posicion/indice: num_rows="dynamic" permite borrar una fila de la mitad
de la tabla, lo que corre de posicion a todas las filas siguientes sin
que hayan cambiado en nada -- una primera version de este autocompletado
comparaba por posicion y por eso sobreescribia mal la descripcion en ese
escenario (test_borrar_fila_del_medio_no_reescribe_las_que_no_cambiaron)."""
import pandas as pd

from app_ui import _asignar_fila_ids_especificaciones_tecnicas, _autocompletar_descripcion_cpc, _cargar_catalogo_cpc


def _df_items(filas: list[dict]) -> pd.DataFrame:
    columnas = ["Ítem", "Tipo", "Descripción", "Número CPC", "Descripción CPC", "_fila_id"]
    return pd.DataFrame(filas, columns=columnas)


class _SessionStateFalso(dict):
    """st.session_state real soporta tanto acceso tipo dict como tipo
    atributo; un dict comun no soporta lo segundo, asi que estas pruebas
    de _asignar_fila_ids_especificaciones_tecnicas (que usa `st.session_state.x += 1`)
    necesitan un doble minimo que soporte ambos."""

    def __getattr__(self, nombre):
        try:
            return self[nombre]
        except KeyError:
            raise AttributeError(nombre)

    def __setattr__(self, nombre, valor):
        self[nombre] = valor


class TestCargarCatalogoCPC:
    def test_catalogo_no_vacio_y_con_entradas_conocidas(self):
        catalogo = _cargar_catalogo_cpc()

        assert len(catalogo) > 10_000
        assert catalogo["011200011"] == "SEMILLA DE MAIZ-108, HIBRIDO(A)"


class TestAsignarFilaIds:
    def test_filas_sin_id_reciben_uno_nuevo_y_no_se_repiten(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", _SessionStateFalso(especificaciones_tecnicas_siguiente_fila_id=0), raising=False)
        df = _df_items(
            [
                {"Ítem": 1, "Tipo": "Bien", "Descripción": "A", "Número CPC": "", "Descripción CPC": "", "_fila_id": pd.NA},
                {"Ítem": 2, "Tipo": "Bien", "Descripción": "B", "Número CPC": "", "Descripción CPC": "", "_fila_id": pd.NA},
            ]
        )

        resultado = _asignar_fila_ids_especificaciones_tecnicas(df)

        assert resultado["_fila_id"].notna().all()
        assert resultado["_fila_id"].nunique() == 2

    def test_filas_con_id_existente_lo_conservan(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", _SessionStateFalso(especificaciones_tecnicas_siguiente_fila_id=5), raising=False)
        df = _df_items([{"Ítem": 1, "Tipo": "Bien", "Descripción": "A", "Número CPC": "", "Descripción CPC": "", "_fila_id": 3}])

        resultado = _asignar_fila_ids_especificaciones_tecnicas(df)

        assert resultado.loc[0, "_fila_id"] == 3


class TestAutocompletarDescripcionCPC:
    def test_fila_nueva_con_codigo_valido_se_autocompleta(self):
        catalogo = {"011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)"}
        df_anterior = _df_items([])
        df_nuevo = _df_items(
            [{"Ítem": 1, "Tipo": "Bien", "Descripción": "", "Número CPC": "011200011", "Descripción CPC": "", "_fila_id": 1}]
        )

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == "SEMILLA DE MAIZ-108, HIBRIDO(A)"
        assert no_encontrados == []

    def test_fila_nueva_con_codigo_inexistente_no_sobreescribe_y_reporta(self):
        catalogo = {"011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)"}
        df_anterior = _df_items([])
        df_nuevo = _df_items(
            [{"Ítem": 1, "Tipo": "Bien", "Descripción": "", "Número CPC": "999999999", "Descripción CPC": "", "_fila_id": 1}]
        )

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == ""
        assert no_encontrados == ["999999999"]

    def test_codigo_sin_cambios_no_sobreescribe_descripcion_manual(self):
        catalogo = {"011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)"}
        fila = {
            "Ítem": 1,
            "Tipo": "Bien",
            "Descripción": "",
            "Número CPC": "011200011",
            "Descripción CPC": "Descripcion propia del usuario",
            "_fila_id": 1,
        }
        df_anterior = _df_items([fila])
        df_nuevo = _df_items([fila])

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == "Descripcion propia del usuario"
        assert no_encontrados == []

    def test_codigo_cambiado_actualiza_descripcion_de_esa_fila(self):
        catalogo = {
            "011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
            "011200012": "SEMILLA DE MAIZ-109, HIBRIDO(A)",
        }
        df_anterior = _df_items(
            [
                {
                    "Ítem": 1,
                    "Tipo": "Bien",
                    "Descripción": "",
                    "Número CPC": "011200011",
                    "Descripción CPC": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
                    "_fila_id": 1,
                }
            ]
        )
        df_nuevo = _df_items(
            [
                {
                    "Ítem": 1,
                    "Tipo": "Bien",
                    "Descripción": "",
                    "Número CPC": "011200012",
                    "Descripción CPC": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
                    "_fila_id": 1,
                }
            ]
        )

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == "SEMILLA DE MAIZ-109, HIBRIDO(A)"
        assert no_encontrados == []

    def test_codigo_vacio_no_dispara_autocompletado(self):
        catalogo = {"011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)"}
        df_anterior = _df_items([])
        df_nuevo = _df_items(
            [{"Ítem": 1, "Tipo": "Bien", "Descripción": "", "Número CPC": "", "Descripción CPC": "", "_fila_id": 1}]
        )

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == ""
        assert no_encontrados == []

    def test_varias_filas_solo_recalcula_la_que_cambio(self):
        catalogo = {
            "011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
            "011200012": "SEMILLA DE MAIZ-109, HIBRIDO(A)",
        }
        df_anterior = _df_items(
            [
                {
                    "Ítem": 1,
                    "Tipo": "Bien",
                    "Descripción": "",
                    "Número CPC": "011200011",
                    "Descripción CPC": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
                    "_fila_id": 1,
                },
                {"Ítem": 2, "Tipo": "Bien", "Descripción": "", "Número CPC": "", "Descripción CPC": "", "_fila_id": 2},
            ]
        )
        df_nuevo = _df_items(
            [
                {
                    "Ítem": 1,
                    "Tipo": "Bien",
                    "Descripción": "",
                    "Número CPC": "011200011",
                    "Descripción CPC": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
                    "_fila_id": 1,
                },
                {"Ítem": 2, "Tipo": "Bien", "Descripción": "", "Número CPC": "011200012", "Descripción CPC": "", "_fila_id": 2},
            ]
        )

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == "SEMILLA DE MAIZ-108, HIBRIDO(A)"
        assert resultado.loc[1, "Descripción CPC"] == "SEMILLA DE MAIZ-109, HIBRIDO(A)"
        assert no_encontrados == []

    def test_borrar_fila_del_medio_no_reescribe_las_que_no_cambiaron(self):
        """Reproduce el bug real encontrado al probar con un dataframe
        simulado: si se comparara por POSICION en vez de por '_fila_id',
        borrar la fila del medio correria de indice a la ultima fila y su
        codigo (sin cambios de verdad) se compararia contra un indice
        vacio, disparando un autocompletado indebido que pisaria la
        descripcion que el usuario ya habia corregido a mano."""
        catalogo = {
            "011200011": "SEMILLA DE MAIZ-108, HIBRIDO(A)",
            "011200012": "SEMILLA DE MAIZ-109, HIBRIDO(A)",
            "011200013": "SEMILLA DE MAIZ-156, HIBRIDO(A)",
        }
        df_anterior = _df_items(
            [
                {"Ítem": 1, "Tipo": "Bien", "Descripción": "A", "Número CPC": "011200011", "Descripción CPC": "desc manual A", "_fila_id": 1},
                {"Ítem": 2, "Tipo": "Bien", "Descripción": "B", "Número CPC": "011200012", "Descripción CPC": "desc manual B", "_fila_id": 2},
                {"Ítem": 3, "Tipo": "Bien", "Descripción": "C", "Número CPC": "011200013", "Descripción CPC": "desc manual C", "_fila_id": 3},
            ]
        )
        # el usuario borro la fila del medio (_fila_id=2): la fila C ahora
        # queda en la posicion 1 en vez de 2, pero es la MISMA fila (mismo
        # _fila_id=3) y su codigo CPC no cambio.
        df_nuevo = _df_items(
            [
                {"Ítem": 1, "Tipo": "Bien", "Descripción": "A", "Número CPC": "011200011", "Descripción CPC": "desc manual A", "_fila_id": 1},
                {"Ítem": 2, "Tipo": "Bien", "Descripción": "C", "Número CPC": "011200013", "Descripción CPC": "desc manual C", "_fila_id": 3},
            ]
        )

        resultado, no_encontrados = _autocompletar_descripcion_cpc(df_nuevo, df_anterior, catalogo)

        assert resultado.loc[0, "Descripción CPC"] == "desc manual A"
        assert resultado.loc[1, "Descripción CPC"] == "desc manual C"
        assert no_encontrados == []
        assert len(resultado) == 2
