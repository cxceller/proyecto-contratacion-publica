"""App minima para probar la pantalla de login con streamlit.testing.v1.AppTest."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from ui.autenticacion import requerir_login  # noqa: E402

requerir_login()
st.write("ENTRO")
