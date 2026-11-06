"""Restaura un respaldo creado por el reset completo (Zona de peligro).

Uso (desde la raiz del proyecto):

    # 1) Ver que respaldos hay (en disco, o en Cloud Storage con --origen gcs)
    .venv/Scripts/python.exe scripts/restaurar_respaldo.py --listar

    # 2) Ver que se haria (NO modifica nada)
    .venv/Scripts/python.exe scripts/restaurar_respaldo.py 20260101_120000

    # 3) Aplicar. Antes se guarda la BD actual en respaldos/pre_restauracion_<ts>/
    .venv/Scripts/python.exe scripts/restaurar_respaldo.py 20260101_120000 --confirmar

Origen: por defecto "local" (carpeta respaldos/) y "gcs" cuando corre en Cloud Run
(K_SERVICE). `--origen gcs` baja el respaldo del bucket SERCOP_DB_BUCKET
(prefijo respaldos/), verifica sus checksums y restaura desde esa copia. Desde un
equipo local hace falta un token: `export GCS_ACCESS_TOKEN=$(gcloud auth print-access-token)`.

Detiene antes la app (API y Streamlit): restaurar mientras otra conexion
escribe puede fallar por bloqueo. Restaura TODA la base (borradores incluidos:
los creados despues del respaldo se pierden, de ahi la copia previa) y copia
los .docx de reportes que falten (--sobrescribir-reportes para pisar los
existentes)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import reset, respaldo_gcs  # noqa: E402
from src.respaldo_gcs import RespaldoRemotoError  # noqa: E402
from src.restauracion import RespaldoInvalidoError, restaurar  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("respaldo", nargs="?", help="Nombre del respaldo (ej. 20260101_120000)")
    parser.add_argument("--listar", action="store_true", help="Lista los respaldos disponibles")
    parser.add_argument("--origen", choices=("local", "gcs"), default=None)
    parser.add_argument("--confirmar", action="store_true", help="Aplica la restauracion (sin esto solo informa)")
    parser.add_argument("--sobrescribir-reportes", action="store_true")
    args = parser.parse_args()
    origen = args.origen or ("gcs" if respaldo_gcs.en_cloud_run() else "local")

    try:
        if args.listar:
            if origen == "gcs":
                carpetas = respaldo_gcs.listar_respaldos()
            else:
                base = reset.DIRECTORIO_RESPALDOS
                carpetas = (
                    sorted(p.name for p in base.iterdir() if (p / "contrataciones.db").is_file())
                    if base.exists()
                    else []
                )
            print("\n".join(carpetas) if carpetas else "No hay respaldos.")
            return 0
        if not args.respaldo:
            parser.error("indica el respaldo o usa --listar")

        resultado = restaurar(
            args.respaldo,
            confirmar=args.confirmar,
            sobrescribir_reportes=args.sobrescribir_reportes,
            origen=origen,
        )
    except (RespaldoInvalidoError, RespaldoRemotoError) as exc:
        print(f"Respaldo no valido: {exc}", file=sys.stderr)
        return 1

    for clave, valor in resultado.items():
        print(f"{clave}: {valor}")
    if not resultado["aplicado"]:
        print("\nNo se modifico nada. Agrega --confirmar para aplicar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
