import logging
import os
from pathlib import Path
import shutil
import subprocess

import uvicorn

from app.core.config import get_settings
from app.core.letsencrypt import ensure_self_signed_certificate


logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    settings = get_settings()
    level_name = settings.app_log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _run_alembic(*args: str) -> None:
    alembic_path = shutil.which("alembic")
    if not alembic_path:
        raise RuntimeError("Alembic CLI was not found in PATH")

    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo_root) if not current_pythonpath else f"{repo_root}:{current_pythonpath}"

    command = [alembic_path, "-c", str(repo_root / "alembic.ini"), *args]
    subprocess.run(command, check=True, cwd=repo_root, env=env)
def prepare_database() -> None:
    settings = get_settings()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Applying database migrations")
    _run_alembic("upgrade", "head")


def main() -> None:
    _configure_logging()
    prepare_database()

    settings = get_settings()
    cert_path = Path(settings.ssl_certfile)
    key_path = Path(settings.ssl_keyfile)
    ensure_self_signed_certificate(cert_path, key_path)

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )


if __name__ == "__main__":
    main()