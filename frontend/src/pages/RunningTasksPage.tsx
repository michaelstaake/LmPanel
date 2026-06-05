import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { cancelRunningTask, fetchRunningTasks, type RunningTaskRecord } from "../lib/api";

const POLL_INTERVAL_MS = 2000;

function formatTaskType(taskType: string): string {
  if (taskType === "chat") return "Chat request";
  if (taskType === "model_fetch") return "Model fetch";
  if (taskType === "model_upload") return "Model upload";
  return taskType;
}

function formatTimestamp(value: number): string {
  return new Date(value * 1000).toLocaleString();
}

export default function RunningTasksPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [tasks, setTasks] = useState<RunningTaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancelingIds, setCancelingIds] = useState<string[]>([]);

  useEffect(() => {
    if (!token) {
      setTasks([]);
      setLoading(false);
      return;
    }

    let active = true;

    const load = async (showLoadState: boolean) => {
      if (showLoadState) {
        setLoading(true);
      }
      try {
        const response = await fetchRunningTasks(token);
        if (active) {
          setTasks(response);
        }
      } catch (error) {
        if (active) {
          showError(error instanceof Error ? error.message : "Failed to load running tasks", { id: "tasks-load-error" });
        }
      } finally {
        if (active && showLoadState) {
          setLoading(false);
        }
      }
    };

    void load(true);
    const intervalId = window.setInterval(() => {
      void load(false);
    }, POLL_INTERVAL_MS);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [showError, token]);

  async function handleCancel(task: RunningTaskRecord) {
    if (!token || cancelingIds.includes(task.task_id)) {
      return;
    }

    setCancelingIds((current) => [...current, task.task_id]);
    try {
      await cancelRunningTask(task.task_id, token);
      setTasks((current) => current.filter((item) => item.task_id !== task.task_id));
      showSuccess(`Cancelled ${task.description}.`, { id: `task-cancel-${task.task_id}` });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to cancel task", { id: `task-cancel-error-${task.task_id}` });
    } finally {
      setCancelingIds((current) => current.filter((id) => id !== task.task_id));
    }
  }

  return (
    <div className="grid gap-4">
      <div className="rounded-2xl border border-black/10 bg-white/80 p-4 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-black/80">Running tasks</h2>
            <p className="text-sm text-black/55">Active chat requests, model fetches, and model uploads.</p>
          </div>
          <div className="rounded-full bg-black/5 px-3 py-1 text-xs font-semibold text-black/55">
            {tasks.length} active
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-black/10 bg-white/80 shadow-sm backdrop-blur">
        {loading ? (
          <p className="p-6 text-center text-sm text-black/50">Loading running tasks…</p>
        ) : tasks.length === 0 ? (
          <p className="p-6 text-center text-sm text-black/50">No active tasks.</p>
        ) : (
          <div className="divide-y divide-black/5">
            {tasks.map((task) => {
              const progressPercent = Math.max(0, Math.min(100, Math.round(task.progress * 100)));
              const isCanceling = cancelingIds.includes(task.task_id);
              return (
                <div key={task.task_id} className="grid gap-3 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                  <div className="grid gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-black/5 px-2.5 py-1 text-xs font-semibold text-black/65">
                        {formatTaskType(task.task_type)}
                      </span>
                      <span className="text-sm font-semibold text-black/80">{task.description}</span>
                    </div>

                    <div className="grid gap-1 text-xs text-black/55 md:grid-cols-3">
                      <span>Started {formatTimestamp(task.created_at)}</span>
                      <span>Model {task.metadata.model ?? task.metadata.file_name ?? "—"}</span>
                      <span>Status {task.status}</span>
                    </div>

                    <div className="grid gap-1.5">
                      <div className="h-2 overflow-hidden rounded-full bg-black/10">
                        <div className="h-full rounded-full bg-ink transition-all" style={{ width: `${progressPercent}%` }} />
                      </div>
                      <div className="text-xs text-black/50">{progressPercent}%</div>
                    </div>
                  </div>

                  <div className="md:justify-self-end">
                    <button
                      type="button"
                      onClick={() => void handleCancel(task)}
                      disabled={isCanceling}
                      className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isCanceling ? "Cancelling…" : "Cancel"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
