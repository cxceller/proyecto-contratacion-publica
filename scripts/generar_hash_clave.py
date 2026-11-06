"""Genera el hash argon2id de la clave de la UI para APP_CLAVE_HASH (.env).

Uso (desde la raiz del proyecto):

    .venv/Scripts/python.exe scripts/generar_hash_clave.py

Pide la clave sin mostrarla en pantalla (dos veces), exige un largo minimo y
imprime la linea lista para pegar en .env. La clave en si NUNCA se guarda ni
se imprime."""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.login import LARGO_MINIMO_CLAVE, hash_clave  # noqa: E402


def main() -> int:
    clave = getpass.getpass("Nueva clave: ")
    if len(clave) < LARGO_MINIMO_CLAVE:
        print(f"La clave debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.", file=sys.stderr)
        return 1
    if clave != getpass.getpass("Repite la clave: "):
        print("Las claves no coinciden.", file=sys.stderr)
        return 1
    # Comillas simples: el hash contiene '$' y python-dotenv respeta el literal.
    print("\nPega esta linea en tu .env (y borra APP_CLAVE, ya no se usa):\n")
    print(f"APP_CLAVE_HASH='{hash_clave(clave)}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
