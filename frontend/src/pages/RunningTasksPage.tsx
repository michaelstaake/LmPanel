import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { cancelRunningTask, fetchRunningTasks, type RunningTaskRecord } from "../lib/api";
import SettingsLayout from "./SettingsLayout";

const POLL_INTERVAL_MS = 2000;

function formatTaskType(taskType: string): string {
  if (taskType === "chat") return "Chat";
  if (taskType === "model_fetch") return "Model fetch";
  if (taskType === "model_upload") return "Model upload";
  return taskType;
}

function formatTimestamp(value: number): string {
  return new Date(value * 1000).toLocaleTimeString();
}

function formatDuration(created_at: number): string {
  const elapsed = Math.round((Date.now() / 1000 - created_at));
  if (elapsed < 60) return `${elapsed}s`;
  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  if (seconds === 0) return `${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

export default function RunningTasksPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [tasks, setTasks] = useState<RunningTaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancelingIds, setCancelingIds] = useState<string[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

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

  const groups = useMemo(() => {
    const map = new Map<string, RunningTaskRecord[]>();

    for (const task of tasks) {
      const username = String(task.metadata.username ?? task.metadata.user_id ?? "System");
      const group = map.get(username) ?? [];
      group.push(task);
      map.set(username, group);
    }

    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [tasks]);

  useEffect(() => {
    const allExpanded = groups.length > 0;
    const newState: Record<string, boolean> = {};
    for (const [username] of groups) {
      if (newState[username] === undefined) {
        newState[username] = allExpanded;
      }
    }
    setExpandedGroups(newState);
  }, [groups]);

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

  function toggleGroup(username: string) {
    setExpandedGroups((current) => ({ ...current, [username]: !current[username] }));
  }

  function progressPercent(task: RunningTaskRecord): number {
    return Math.max(0, Math.min(100, Math.round(task.progress * 100)));
  }

  function progressColor(task: RunningTaskRecord): string {
    const pct = progressPercent(task);
    if (pct >= 100) return "bg-green-500";
    if (pct > 60) return "bg-ink";
    if (pct > 30) return "bg-amber-500";
    return "bg-red-400";
  }

  return (
    <SettingsLayout title="Running Tasks">
      <div className="grid gap-4">
      <div>
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

      {loading ? (
        <div className="rounded-2xl border border-black/10 bg-white/80 p-6 shadow-sm backdrop-blur">
          <p className="text-center text-sm text-black/50">Loading running tasks…</p>
        </div>
      ) : tasks.length === 0 ? (
        <div className="rounded-2xl border border-black/10 bg-white/80 p-6 shadow-sm backdrop-blur">
          <p className="text-center text-sm text-black/50">No active tasks.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map(([username, groupTasks]) => {
            const isExpanded = expandedGroups[username] ?? true;
            return (
              <div key={username} className="overflow-hidden rounded-2xl border border-black/10 bg-white/80 shadow-sm backdrop-blur">
                <button
                  type="button"
                  onClick={() => toggleGroup(username)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-black/[0.02]"
                >
                  <span className="text-sm font-semibold text-black/70">{username}</span>
                  <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs font-semibold text-black/50">{groupTasks.length}</span>
                  <svg
                    className={`h-4 w-4 text-black/40 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {isExpanded && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-t border-black/10 bg-black/5 text-left text-xs font-semibold text-black/60">
                          <th className="px-4 py-2.5">Task</th>
                          <th className="px-4 py-2.5">Duration</th>
                          <th className="px-4 py-2.5">Progress</th>
                          <th className="px-4 py-2.5">Status</th>
                          <th className="px-4 py-2.5 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-black/5">
                        {groupTasks.map((task) => {
                          const pct = progressPercent(task);
                          const isCanceling = cancelingIds.includes(task.task_id);
                          return (
                            <tr key={task.task_id} className="hover:bg-black/[0.02]">
                              <td className="px-4 py-2.5">
                                <div className="flex items-center gap-2">
                                  <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs font-semibold text-black/60">
                                    {formatTaskType(task.task_type)}
                                  </span>
                                  <span className="text-black/80">{task.description}</span>
                                </div>
                                {task.metadata.file_name && (
                                  <div className="mt-1 text-xs text-black/40 font-mono truncate max-w-xs" title={task.metadata.file_name as string}>
                                    {task.metadata.file_name as string}
                                  </div>
                                )}
                              </td>
                              <td className="px-4 py-2.5 text-xs text-black/50 font-mono whitespace-nowrap">
                                {formatDuration(task.created_at)}
                              </td>
                              <td className="px-4 py-2.5">
                                <div className="flex items-center gap-2">
                                  <div className="h-1.5 w-20 overflow-hidden rounded-full bg-black/10">
                                    <div
                                      className={`h-full rounded-full transition-all ${progressColor(task)}`}
                                      style={{ width: `${pct}%` }}
                                    />
                                  </div>
                                  <span className="text-xs text-black/50 font-mono w-8 text-right">{pct}%</span>
                                </div>
                              </td>
                              <td className="px-4 py-2.5">
                                <span className={`text-xs font-semibold ${
                                  task.status === "running" ? "text-green-600" :
                                  task.status === "error" ? "text-red-600" :
                                  task.status === "cancelled" ? "text-amber-600" :
                                  "text-black/50"
                                }`}>
                                  {task.status}
                                </span>
                              </td>
                              <td className="px-4 py-2.5 text-right">
                                <button
                                  type="button"
                                  onClick={() => void handleCancel(task)}
                                  disabled={isCanceling}
                                  className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  {isCanceling ? "Cancelling…" : "Cancel"}
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      </div>
    </SettingsLayout>
  );
}
