"""Capa Streamlit de la autenticacion (la logica -- argon2id, bloqueo
temporal, fail-closed -- vive en src/login.py, sin Streamlit).

- `requerir_login()` va al inicio de CADA pagina (app_ui.py y
  pages/Reportes.py): sin sesion valida muestra el formulario y detiene el
  script con st.stop(). La sesion caduca tras 30 min de inactividad.
- `confirmar_con_clave()` vuelve a pedir la clave en acciones destructivas
  (reset/BORRAR, borrado de borradores) aunque haya sesion activa, y deja
  una traza de auditoria (quien, que, cuando, resultado) en el log."""
import time

import streamlit as st

from src import login
from src.logging_config import obtener_logger

logger = obtener_logger(__name__)

K_AUTENTICADO = "auth_autenticado"
K_USUARIO = "auth_usuario"
K_ULTIMA_ACTIVIDAD = "auth_ultima_actividad"


def auditar(accion: str, resultado: str) -> None:
    """Traza de auditoria: usuario, accion y resultado (la hora la pone el
    formato del logger). Nunca se registra la clave."""
    usuario = st.session_state.get(K_USUARIO) or "desconocido"
    logger.info("AUDITORIA accion=%s usuario=%s resultado=%s", accion, usuario, resultado)


def cerrar_sesion(motivo: str = "cierre") -> None:
    if st.session_state.get(K_AUTENTICADO):
        auditar("logout", motivo)
    for clave in (K_AUTENTICADO, K_USUARIO, K_ULTIMA_ACTIVIDAD):
        st.session_state.pop(clave, None)


def _sesion_vigente() -> bool:
    """True si hay sesion y no paso el limite de inactividad (refresca la
    marca de actividad); si expiro, la cierra."""
    if not st.session_state.get(K_AUTENTICADO):
        return False
    ahora = time.time()
    if ahora - st.session_state.get(K_ULTIMA_ACTIVIDAD, 0) > login.INACTIVIDAD_MAX_S:
        cerrar_sesion("inactividad")
        st.session_state["auth_sesion_expirada"] = True
        return False
    st.session_state[K_ULTIMA_ACTIVIDAD] = ahora
    return True


def _mensaje_bloqueo() -> str:
    segundos = login.segundos_de_bloqueo()
    minutos = max(1, -(-segundos // 60))
    return f"Demasiados intentos fallidos. Vuelve a intentarlo en {minutos} min."


def requerir_login() -> None:
    """Debe llamarse al inicio de cada pagina, antes de renderizar datos."""
    if _sesion_vigente():
        return

    st.title(":material/lock: SERCOP Analytics")
    st.caption("Acceso restringido.")

    if st.session_state.pop("auth_sesion_expirada", False):
        st.warning("Tu sesión expiró por inactividad. Vuelve a iniciar sesión.")

    if not login.acceso_configurado():
        st.error(
            "Acceso no configurado: define APP_USUARIO y APP_CLAVE_HASH en el archivo .env "
            "(genera el hash con `scripts/generar_hash_clave.py`)."
        )
        st.stop()

    bloqueado = login.segundos_de_bloqueo() > 0
    if bloqueado:
        st.error(_mensaje_bloqueo())

    with st.form("form_login"):
        usuario = st.text_input("Usuario", max_chars=100)
        clave = st.text_input("Clave", type="password", max_chars=200)
        enviado = st.form_submit_button("Ingresar", type="primary", width="stretch", disabled=bloqueado)

    if enviado:
        resultado = login.autenticar(usuario, clave)
        if resultado == login.OK:
            st.session_state[K_AUTENTICADO] = True
            st.session_state[K_USUARIO] = usuario
            st.session_state[K_ULTIMA_ACTIVIDAD] = time.time()
            auditar("login", "ok")
            st.rerun()
        elif resultado == login.BLOQUEADO:
            logger.warning("Intento de login durante el bloqueo temporal")
            st.error(_mensaje_bloqueo())
        else:
            logger.warning("Login fallido")
            if login.segundos_de_bloqueo() > 0:
                st.error(_mensaje_bloqueo())
            else:
                st.error("Usuario o clave incorrectos.")

    st.stop()


def confirmar_con_clave(accion: str, clave: str) -> bool:
    """Re-autentica al usuario de la sesion para `accion` (ej. "reset_completo",
    "eliminar_borrador"). True solo si la clave es correcta y no hay bloqueo.
    Registra el resultado en la auditoria y muestra el error correspondiente."""
    resultado = login.reautenticar(clave)
    auditar(accion, resultado)
    if resultado == login.OK:
        return True
    if resultado == login.BLOQUEADO or login.segundos_de_bloqueo() > 0:
        st.error(_mensaje_bloqueo())
    else:
        st.error("Clave incorrecta. No se realizó la acción.")
    return False
