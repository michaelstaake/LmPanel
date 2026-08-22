import os
import secrets

import docker
from fastapi import Depends, FastAPI, Header, HTTPException, Query


app = FastAPI(title="LmPanel Docker Control")


def _authorize(x_docker_control_secret: str | None = Header(default=None)) -> None:
    expected = os.environ.get("DOCKER_CONTROL_SECRET", "").strip()
    if expected and not secrets.compare_digest(x_docker_control_secret or "", expected):
        raise HTTPException(status_code=401, detail="Invalid control service credentials")


def _allowed_container_names() -> set[str]:
    configured = os.environ.get(
        "DOCKER_CONTROL_CONTAINERS",
        "lmpanel-backend,lmpanel-frontend,lmpanel-inference,lmpanel-docker-control",
    )
    return {name.strip() for name in configured.split(",") if name.strip()}


def _get_allowed_container(client, container_name: str):
    if container_name not in _allowed_container_names():
        raise HTTPException(status_code=404, detail="Container not found")
    try:
        return client.containers.get(container_name)
    except docker.errors.NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/containers", dependencies=[Depends(_authorize)])
def list_containers() -> dict:
    client = docker.from_env()
    try:
        running_names = {container.name for container in client.containers.list(all=True)}
        return {"containers": sorted(_allowed_container_names() & running_names)}
    finally:
        client.close()


@app.get("/containers/{container_name}/logs", dependencies=[Depends(_authorize)])
def container_logs(
    container_name: str,
    tail: int = Query(default=200, ge=1, le=1000),
) -> dict:
    client = docker.from_env()
    try:
        container = _get_allowed_container(client, container_name)
        raw: bytes = container.logs(tail=tail, timestamps=True)
        return {
            "container": container_name,
            "lines": raw.decode("utf-8", errors="replace").splitlines(),
        }
    finally:
        client.close()


@app.post("/certificates/reload", dependencies=[Depends(_authorize)])
def reload_frontend_certificate() -> dict:
    client = docker.from_env()
    try:
        frontend_name = os.environ.get("DOCKER_FRONTEND_CONTAINER", "lmpanel-frontend")
        frontend = _get_allowed_container(client, frontend_name)
        result = frontend.exec_run(["nginx", "-s", "reload"])
        if result.exit_code != 0:
            output = (result.output or b"").decode("utf-8", errors="replace")
            raise HTTPException(status_code=502, detail=f"nginx reload failed: {output}")
        return {"status": "ok"}
    finally:
        client.close()
