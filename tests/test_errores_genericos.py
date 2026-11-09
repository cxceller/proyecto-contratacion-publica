"""Regla de seguridad: la UI nunca interpola excepciones en lo que ve el usuario (st.error(f"...{exc}"))."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVOS = [RAIZ / "app_ui.py", *sorted((RAIZ / "ui").glob("*.py")), *sorted((RAIZ / "pages").glob("*.py"))]
PATRON = re.compile(r"st\.(?:error|warning|info|success|exception)\(\s*f[\"'][^\n]*\{(?:exc|e|err|ex|exception)[}.\s!:]")


def test_ninguna_excepcion_se_interpola_en_mensajes_de_usuario():
    ofensores = [
        f"{a.name}:{i}"
        for a in ARCHIVOS
        for i, linea in enumerate(a.read_text(encoding="utf-8").splitlines(), 1)
        if PATRON.search(linea)
    ]
    assert ofensores == []


def test_la_ui_no_usa_st_exception():
    for a in ARCHIVOS:
        assert "st.exception(" not in a.read_text(encoding="utf-8"), a.name


def test_rango_de_fechas_invalido_usa_mensaje_fijo():
    fuente = (RAIZ / "ui" / "reportes.py").read_text(encoding="utf-8")
    assert 'st.error(f"Datos inválidos: {exc}")' not in fuente
    assert 'logger.exception("Rango de fechas invalido en Reportes")' in fuente
