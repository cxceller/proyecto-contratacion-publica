"""Logica de autenticacion de la UI (sin Streamlit, para poder probarla).

- Clave: hash argon2id (argon2-cffi), nunca texto plano. `APP_CLAVE_HASH` en
  .env; se genera con scripts/generar_hash_clave.py.
- Bloqueo temporal creciente tras 5 fallos seguidos: 1 min, luego 5 min,
  luego 15 min (el tope se mantiene; NUNCA es permanente). Se persiste en un
  SQLite aparte (no en session_state, que el atacante reinicia con solo
  recargar la pagina). Es un contador global: la app tiene un unico usuario y
  Streamlit no expone la IP del cliente de forma confiable; el costo es que un
  atacante puede bloquear temporalmente al usuario legitimo, no entrar.
- Fail-closed: sin APP_USUARIO o APP_CLAVE_HASH nadie entra.
"""
import os
import secrets
import sqlite3
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from src import database
from src.logging_config import obtener_logger

logger = obtener_logger(__name__)

MAX_FALLOS = 5
BLOQUEOS_S = (60, 300, 900)
INACTIVIDAD_MAX_S = 30 * 60
LARGO_MINIMO_CLAVE = 12

_hasher = PasswordHasher()  # argon2id por defecto


def hash_clave(clave: str) -> str:
    return _hasher.hash(clave)


def verificar_clave(clave: str, hash_almacenado: str | None) -> bool:
    """True solo si `clave` corresponde a `hash_almacenado` (argon2id)."""
    if not hash_almacenado:
        return False
    try:
        return _hasher.verify(hash_almacenado, clave or "")
    except (VerificationError, InvalidHashError):
        return False


def hash_necesita_actualizarse(hash_almacenado: str | None) -> bool:
    """True si el hash usa parametros de argon2 mas debiles que los actuales de la libreria.
    NO se reescribe solo: el hash vive en el entorno/Secret Manager y la app no debe modificarlo."""
    if not hash_almacenado:
        return False
    try:
        return _hasher.check_needs_rehash(hash_almacenado)
    except (InvalidHashError, VerificationError):
        return False


_aviso_rehash_emitido = False


def _avisar_si_hay_que_regenerar(hash_almacenado: str | None) -> None:
    """Tras un login correcto: un unico aviso por proceso (sin datos sensibles) si el hash es antiguo."""
    global _aviso_rehash_emitido
    if _aviso_rehash_emitido or not hash_necesita_actualizarse(hash_almacenado):
        return
    _aviso_rehash_emitido = True
    logger.warning("APP_CLAVE_HASH usa parámetros antiguos; regenéralo con scripts/generar_hash_clave.py")


def usuario_configurado() -> str | None:
    return os.environ.get("APP_USUARIO") or None


def hash_configurado() -> str | None:
    return os.environ.get("APP_CLAVE_HASH") or None


def acceso_configurado() -> bool:
    return bool(usuario_configurado() and hash_configurado())


# ---------------------------------------------------------------- bloqueo
def _ruta_estado() -> Path:
    ruta = os.environ.get("LOGIN_STATE_PATH")
    return Path(ruta) if ruta else Path(database.DB_PATH).parent / "login_intentos.sqlite3"


def _conectar() -> sqlite3.Connection:
    ruta = _ruta_estado()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta), timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS estado ("
        "id TEXT PRIMARY KEY, fallos INTEGER NOT NULL, nivel INTEGER NOT NULL, bloqueado_hasta REAL NOT NULL)"
    )
    return conn


def _leer(conn: sqlite3.Connection) -> tuple[int, int, float]:
    fila = conn.execute("SELECT fallos, nivel, bloqueado_hasta FROM estado WHERE id = 'global'").fetchone()
    return fila if fila else (0, 0, 0.0)


def segundos_de_bloqueo(ahora: float | None = None) -> int:
    """Segundos restantes de bloqueo (0 si se puede intentar)."""
    ahora = time.time() if ahora is None else ahora
    conn = _conectar()
    try:
        _, _, hasta = _leer(conn)
    finally:
        conn.close()
    return max(0, int(hasta - ahora + 0.999))


def registrar_fallo(ahora: float | None = None) -> int:
    """Suma un fallo; al llegar a MAX_FALLOS bloquea (1/5/15 min, creciente).
    Devuelve los segundos de bloqueo resultantes (0 si aun no se bloquea)."""
    ahora = time.time() if ahora is None else ahora
    conn = _conectar()
    try:
        with conn:
            fallos, nivel, hasta = _leer(conn)
            fallos += 1
            if fallos >= MAX_FALLOS:
                duracion = BLOQUEOS_S[min(nivel, len(BLOQUEOS_S) - 1)]
                hasta, nivel, fallos = ahora + duracion, nivel + 1, 0
            conn.execute(
                "INSERT INTO estado (id, fallos, nivel, bloqueado_hasta) VALUES ('global', ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET fallos = excluded.fallos, nivel = excluded.nivel, "
                "bloqueado_hasta = excluded.bloqueado_hasta",
                (fallos, nivel, hasta),
            )
    finally:
        conn.close()
    return max(0, int(hasta - ahora + 0.999))


def registrar_exito() -> None:
    conn = _conectar()
    try:
        with conn:
            conn.execute("DELETE FROM estado WHERE id = 'global'")
    finally:
        conn.close()


# ------------------------------------------------------------- autenticar
OK = "ok"
INVALIDA = "invalida"
BLOQUEADO = "bloqueado"
NO_CONFIGURADO = "no_configurado"


def autenticar(usuario: str, clave: str, ahora: float | None = None) -> str:
    """Valida usuario + clave aplicando el bloqueo. Devuelve OK, INVALIDA,
    BLOQUEADO o NO_CONFIGURADO. La clave se verifica SIEMPRE (aunque el
    usuario no coincida) para no filtrar por tiempo si el usuario existe."""
    if not acceso_configurado():
        return NO_CONFIGURADO
    if segundos_de_bloqueo(ahora) > 0:
        return BLOQUEADO
    usuario_ok = secrets.compare_digest((usuario or "").encode(), usuario_configurado().encode())
    clave_ok = verificar_clave(clave, hash_configurado())
    if usuario_ok and clave_ok:
        registrar_exito()
        _avisar_si_hay_que_regenerar(hash_configurado())
        return OK
    registrar_fallo(ahora)
    return INVALIDA


def reautenticar(clave: str, ahora: float | None = None) -> str:
    """Re-pide la clave para una accion destructiva (con sesion ya activa):
    mismo bloqueo que el login, usuario = el configurado."""
    return autenticar(usuario_configurado() or "", clave, ahora)
