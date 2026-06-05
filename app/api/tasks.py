from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_admin_user
from app.core.task_manager import task_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks(_: object = Depends(get_admin_user)) -> list[dict]:
    return task_manager.get_tasks()


@router.get("/{task_id}")
def get_task(task_id: str, _: object = Depends(get_admin_user)) -> dict:
    task = task_manager._tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.delete("/{task_id}")
def cancel_task(
    task_id: str,
    _: object = Depends(get_admin_user),
) -> dict:
    if task_manager.cancel_task(task_id):
        return {"status": "ok", "message": f"Task {task_id} cancelled"}
    raise HTTPException(status_code=404, detail="Task not found")
