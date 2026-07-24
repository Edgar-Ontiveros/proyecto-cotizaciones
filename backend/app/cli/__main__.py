"""CLI del proyecto: `uv run python -m app.cli <comando>`."""

import argparse

from app.core.database import SessionLocal
from app.core.logging import configure_logging, logger


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("seed", help="Carga los datos reales de arranque (idempotente)")
    args = parser.parse_args()

    configure_logging()

    if args.comando == "seed":
        from app.cli.seed import run

        with SessionLocal() as db:
            conteos = run(db)
        logger.info("seed_completado", **conteos)


if __name__ == "__main__":
    main()
