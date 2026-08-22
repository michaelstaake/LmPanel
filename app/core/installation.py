import logging
import os
import secrets
import shutil
import stat
import time
from pathlib import Path


logger = logging.getLogger(__name__)
LEGACY_PUBLIC_DIRECTORIES = ("backgrounds", "favicons", "logos")
INSECURE_JWT_SECRETS = {"", "change-me"}
_logged_setup_token = False


def load_or_create_secret(data_dir: str, filename: str, configured_value: str = "") -> str:
    configured_value = configured_value.strip()
    if configured_value and configured_value not in INSECURE_JWT_SECRETS:
        return configured_value

    path = Path(data_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except FileNotFoundError:
        pass

    value = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()

    with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
        secret_file.write(f"{value}\n")
    return value


def ensure_public_storage(data_dir: str) -> Path:
    data_path = Path(data_dir)
    public_path = data_path / "public"
    public_path.mkdir(parents=True, exist_ok=True)

    for directory_name in LEGACY_PUBLIC_DIRECTORIES:
        legacy_path = data_path / directory_name
        destination = public_path / directory_name
        destination.mkdir(parents=True, exist_ok=True)
        if not legacy_path.is_dir():
            continue
        for source in legacy_path.iterdir():
            target = destination / source.name
            if target.exists():
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            else:
                shutil.move(str(source), str(target))
        try:
            legacy_path.rmdir()
        except OSError:
            logger.warning("Could not remove legacy public asset directory %s", legacy_path)

    return public_path


def get_setup_token(data_dir: str, configured_value: str = "") -> str:
    global _logged_setup_token

    token = load_or_create_secret(data_dir, ".setup-token", configured_value)
    if not _logged_setup_token:
        logger.warning(
            "Initial admin setup token: %s (required when setup is not performed from localhost)",
            token,
        )
        _logged_setup_token = True
    return token


def remove_setup_token(data_dir: str) -> None:
    try:
        (Path(data_dir) / ".setup-token").unlink()
    except FileNotFoundError:
        pass


def acquire_setup_claim(data_dir: str) -> Path:
    claim_path = Path(data_dir) / ".setup-claim"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(
                claim_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IRUSR | stat.S_IWUSR,
            )
        except FileExistsError:
            try:
                if time.time() - claim_path.stat().st_mtime > 600:
                    claim_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            raise RuntimeError("Initial admin setup is already in progress")
        with os.fdopen(descriptor, "w", encoding="utf-8") as claim_file:
            claim_file.write(f"{os.getpid()}\n")
        return claim_path
    raise RuntimeError("Initial admin setup is already in progress")
