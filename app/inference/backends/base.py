from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LaunchPlan:
    command: list[str]
    env: dict[str, str]
    health_url: str
    log_prefix: str = "llama"
    post_launch_validate: bool = True


class InferenceBackend(Protocol):
    def build_launch(self, payload: object, port: int, settings: object) -> LaunchPlan:
        ...
