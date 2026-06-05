import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


TERMINAL_TASK_STATUSES = {"completed", "error", "cancelled"}

@dataclass
class TaskInfo:
    task_id: str
    task_type: str  # "chat" | "model_fetch" | "model_upload"
    description: str
    status: str  # "running" | "completed" | "error" | "cancelled"
    progress: float = 0.0  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "error": self.error,
        }

class TaskManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, TaskInfo] = {}
        self._async_tasks: Dict[str, asyncio.Task] = {}

    def add_task(
        self,
        task_id: str,
        task_type: str,
        description: str,
        async_task: Optional[asyncio.Task] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskInfo:
        info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            description=description,
            status="running",
            metadata=metadata or {},
        )
        self._tasks[task_id] = info
        if async_task:
            self._async_tasks[task_id] = async_task
        return info

    def attach_async_task(self, task_id: str, async_task: asyncio.Task) -> None:
        if task_id in self._tasks:
            self._async_tasks[task_id] = async_task

    def update_task(self, task_id: str, **kwargs) -> None:
        if task_id in self._tasks:
            info = self._tasks[task_id]
            for key, value in kwargs.items():
                if hasattr(info, key):
                    setattr(info, key, value)

    def complete_task(self, task_id: str, error: Optional[str] = None) -> None:
        if task_id in self._tasks:
            info = self._tasks[task_id]
            if info.status == "cancelled":
                self._async_tasks.pop(task_id, None)
                return
            info.status = "error" if error else "completed"
            if error:
                info.error = error
            info.progress = 1.0 if not error else 0.0
            self._async_tasks.pop(task_id, None)

    def fail_task(self, task_id: str, error: str) -> None:
        self.complete_task(task_id, error=error)

    def mark_cancelled(self, task_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].status = "cancelled"
            self._tasks[task_id].error = None
            self._tasks[task_id].progress = 0.0
        self._async_tasks.pop(task_id, None)

    def cancel_task(self, task_id: str) -> bool:
        task = self._async_tasks.get(task_id)

        if task_id in self._tasks:
            self.mark_cancelled(task_id)

        if task is not None:
            task.cancel()
            return True

        if task_id in self._tasks:
            return True

        return False

    def get_tasks(self, include_finished: bool = False) -> list[Dict[str, Any]]:
        tasks = self._tasks.values()
        if not include_finished:
            tasks = [task for task in tasks if task.status not in TERMINAL_TASK_STATUSES]
        return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]

    def remove_task(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        self._async_tasks.pop(task_id, None)

# Singleton instance
task_manager = TaskManager()
