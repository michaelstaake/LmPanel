import asyncio
import logging
import os
import re

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GITHUB_REPO_OWNER = "michaelstaake"
GITHUB_REPO_NAME = "LmPanel"

_BUILD_INFO_PATH = "/app/shared/build-info.env"


def _read_build_info() -> tuple[str, str]:
    try:
        with open(_BUILD_INFO_PATH) as f:
            content = f.read()
        commit = ""
        version = ""
        for line in content.splitlines():
            m = re.match(r'VITE_APP_GIT_COMMIT="([^"]*)"', line)
            if m:
                commit = m.group(1)
            m = re.match(r'VITE_APP_VERSION="([^"]*)"', line)
            if m:
                version = m.group(1)
        return commit, version
    except Exception:
        return "", ""


async def check_for_updates() -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            commit_response = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/commits/main",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
        except Exception:
            commit_response = None

        try:
            release_response = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
        except Exception:
            release_response = None

    latest_commit = ""
    latest_version = ""

    if commit_response and commit_response.status_code == 200:
        latest_commit = commit_response.json().get("sha", "")

    if release_response and release_response.status_code == 200:
        latest_version = release_response.json().get("tag_name", "")

    current_commit = os.environ.get("VITE_APP_GIT_COMMIT", "")
    current_version = os.environ.get("VITE_APP_VERSION", "")
    if not current_commit or not current_version:
        file_commit, file_version = _read_build_info()
        if not current_commit:
            current_commit = file_commit
        if not current_version:
            current_version = file_version

    update_available = False
    if latest_commit and current_commit and latest_commit != current_commit:
        update_available = True
    elif latest_version and current_version:
        current_tag = current_version if current_version.startswith("v") else f"v{current_version}"
        if latest_version != current_tag:
            update_available = True

    return {
        "latest_commit": latest_commit,
        "latest_version": latest_version,
        "update_available": update_available,
    }


async def schedule_update_check() -> None:
    while True:
        await asyncio.sleep(86400)
        try:
            from app.core.app_settings import get_or_create_app_settings
            from app.core.db import SessionLocal

            db = SessionLocal()
            try:
                app_settings = get_or_create_app_settings(db)
                if app_settings.update_check_mode == "disabled":
                    continue

                result = await check_for_updates()
                if result and result["update_available"]:
                    logger.info("Update available: commit=%s, version=%s", result["latest_commit"], result["latest_version"])
            finally:
                db.close()
        except Exception:
            logger.exception("Update check failed")
