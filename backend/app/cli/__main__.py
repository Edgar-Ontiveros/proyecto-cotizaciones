"""CLI del proyecto: `uv run python -m app.cli <comando>`."""

import argparse

from app.core.database import SessionLocal
from app.core.logging import configure_logging, logger


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("seed", help="Carga los datos DEMO de arranque (idempotente)")
    sub.add_parser(
        "seed-produccion",
        help="Arranque de PRODUCCIÓN: sucursales, catálogos y los 4 usuarios reales",
    )
    args = parser.parse_args()

    configure_logging()

    if args.comando == "seed":
        from app.cli.seed import run

        with SessionLocal() as db:
            conteos = run(db)
        logger.info("seed_completado", **conteos)
    elif args.comando == "seed-produccion":
        from app.cli.seed_produccion import run as run_produccion

        with SessionLocal() as db:
            conteos, temporales = run_produccion(db)
        if temporales:
            # Contraseñas temporales: se muestran UNA sola vez, aquí.
            print("\nContraseñas temporales (un solo uso, cambio forzado al entrar):")
            for email, password in temporales.items():
                print(f"  {email}: {password}")
            print()
        logger.info("seed_produccion_completado", **conteos)


if __name__ == "__main__":
    main()
