"""Capa Streamlit de la autenticacion (la logica -- argon2id, bloqueo
temporal, fail-closed -- vive en src/login.py, sin Streamlit).

- `requerir_login()` va al inicio de CADA pagina (app_ui.py y
  pages/Reportes.py): sin sesion valida muestra el formulario y detiene el
  script con st.stop(). La sesion caduca tras 30 min de inactividad.
- `confirmar_con_clave()` vuelve a pedir la clave en acciones destructivas
  (reset/BORRAR, borrado de borradores) aunque haya sesion activa, y deja
  una traza de auditoria (quien, que, cuando, resultado) en el log."""
import inspect
import time

import streamlit as st
from streamlit.runtime.scriptrunner import RerunException, StopException

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


MENSAJE_ERROR_GENERICO = "No se pudo completar el acceso en este momento. Inténtalo de nuevo en unos minutos."
MAX_LARGO_USUARIO = 100
MAX_LARGO_CLAVE = 200


def _kwargs_ancho_completo(widget) -> dict:
    """Ancho completo compatible con cualquier Streamlit: `width="stretch"` (>= 1.48)
    o, en versiones anteriores, `use_container_width=True`. Asi el boton de envio
    nunca falla por un kwarg que la version instalada no conoce (en 1.41 eso dejaba
    el formulario sin boton)."""
    parametros = inspect.signature(widget).parameters
    return {"width": "stretch"} if "width" in parametros else {"use_container_width": True}


def _estado_de_acceso() -> tuple[bool, bool]:
    """(configurado, bloqueado) -- tolera fallos del hash/bloqueo: si no se puede
    consultar el bloqueo, se trata como bloqueado (fail-closed) y se registra."""
    try:
        configurado = login.acceso_configurado()
    except Exception:  # noqa: BLE001 -- nunca debe impedir dibujar el formulario
        logger.exception("Fallo al leer la configuracion de acceso")
        return False, True
    if not configurado:
        return False, True
    try:
        return True, login.segundos_de_bloqueo() > 0
    except Exception:  # noqa: BLE001
        logger.exception("Fallo al consultar el bloqueo de intentos")
        return True, True


def requerir_login() -> None:
    """Debe llamarse al inicio de cada pagina, antes de renderizar datos.

    El formulario (con su boton de envio) se dibuja SIEMPRE: todo lo que puede
    fallar (configuracion, bloqueo, autenticacion) va fuera del `with st.form` o
    despues del submit, con try/except y mensaje generico."""
    if _sesion_vigente():
        return

    st.title(":material/lock: SERCOP Analytics")
    st.caption("Acceso restringido.")

    if st.session_state.pop("auth_sesion_expirada", False):
        st.warning("Tu sesión expiró por inactividad. Vuelve a iniciar sesión.")

    configurado, bloqueado = _estado_de_acceso()
    if not configurado:
        st.error(
            "Acceso no configurado: define APP_USUARIO y APP_CLAVE_HASH en el archivo .env "
            "(genera el hash con `scripts/generar_hash_clave.py`)."
        )
    elif bloqueado:
        try:
            st.error(_mensaje_bloqueo())
        except Exception:  # noqa: BLE001
            logger.exception("Fallo al calcular el tiempo de bloqueo")
            st.error(MENSAJE_ERROR_GENERICO)

    with st.form("form_login"):
        usuario = st.text_input("Usuario")
        clave = st.text_input("Clave", type="password")
        enviado = st.form_submit_button(
            "Ingresar",
            type="primary",
            disabled=bloqueado,
            **_kwargs_ancho_completo(st.form_submit_button),
        )

    if enviado and configurado and not bloqueado:
        _procesar_envio(usuario, clave)

    st.stop()


def _procesar_envio(usuario: str, clave: str) -> None:
    """Valida las credenciales enviadas; ningun error interno llega al usuario."""
    try:
        if len(usuario or "") > MAX_LARGO_USUARIO or len(clave or "") > MAX_LARGO_CLAVE:
            resultado = login.INVALIDA  # entradas absurdamente largas: se rechazan sin hashear
            login.registrar_fallo()
        else:
            resultado = login.autenticar(usuario, clave)
        if resultado == login.OK:
            st.session_state[K_AUTENTICADO] = True
            st.session_state[K_USUARIO] = usuario
            st.session_state[K_ULTIMA_ACTIVIDAD] = time.time()
            auditar("login", "ok")
            st.rerun()
        elif resultado == login.BLOQUEADO or login.segundos_de_bloqueo() > 0:
            logger.warning("Intento de login durante el bloqueo temporal")
            st.error(_mensaje_bloqueo())
        else:
            logger.warning("Login fallido")
            st.error("Usuario o clave incorrectos.")
    except (RerunException, StopException):
        raise  # st.rerun()/st.stop() usan excepciones de control: no se tocan
    except Exception:  # noqa: BLE001
        logger.exception("Fallo inesperado al validar el login")
        st.error(MENSAJE_ERROR_GENERICO)


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
