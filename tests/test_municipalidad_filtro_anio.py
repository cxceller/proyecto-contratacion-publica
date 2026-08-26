"""Tests del filtro de Año en la pestaña "Municipalidad de Guayaquil"
(app_ui.py, render_pagina_municipalidad_guayaquil): solo las funciones
puras _anios_disponibles/_filtrar_por_anio, sin depender de Streamlit ni
de la API -- mismo criterio que el resto de tests de app_ui.py."""
from app_ui import _anios_disponibles, _filtrar_por_anio


def _registros(anios: list[str]) -> list[dict]:
    return [{"fecha_publicacion": f"{a}-01-15"} for a in anios]


class TestAniosDisponibles:
    def test_ordena_del_mas_reciente_al_mas_antiguo_sin_duplicados(self):
        registros = _registros(["2024", "2026", "2025", "2026", "2024"])
        assert _anios_disponibles(registros) == ["2026", "2025", "2024"]

    def test_sin_registros_devuelve_lista_vacia(self):
        assert _anios_disponibles([]) == []

    def test_ignora_registros_sin_fecha_publicacion(self):
        registros = [{"fecha_publicacion": "2026-03-01"}, {"fecha_publicacion": None}, {}]
        assert _anios_disponibles(registros) == ["2026"]


class TestFiltrarPorAnio:
    def test_anio_none_devuelve_todo_sin_modificar(self):
        registros = _registros(["2026", "2025"])
        assert _filtrar_por_anio(registros, None) == registros

    def test_filtra_solo_el_anio_pedido(self):
        registros = _registros(["2026", "2025", "2026"])
        filtrados = _filtrar_por_anio(registros, "2025")
        assert filtrados == [{"fecha_publicacion": "2025-01-15"}]

    def test_anio_sin_coincidencias_devuelve_lista_vacia(self):
        registros = _registros(["2026", "2025"])
        assert _filtrar_por_anio(registros, "2020") == []

    def test_ignora_registros_sin_fecha_publicacion(self):
        registros = [{"fecha_publicacion": "2026-03-01"}, {"fecha_publicacion": None}]
        assert _filtrar_por_anio(registros, "2026") == [{"fecha_publicacion": "2026-03-01"}]
