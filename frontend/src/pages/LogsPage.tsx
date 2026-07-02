import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { apiGet } from "../lib/api";
import type { ActivityLogRecord, DockerContainersResponse, DockerLogsResponse, LogsResponse } from "../lib/records";
import SettingsLayout from "./SettingsLayout";

const CATEGORIES = [
  { value: "", label: "All" },
  { value: "auth", label: "Auth" },
  { value: "models", label: "Models" },
  { value: "devices", label: "Devices" },
  { value: "chat", label: "Chat" },
  { value: "admin", label: "Admin" },
];

const TAIL_OPTIONS = [100, 200, 500, 1000];

function eventTypeBadgeClass(eventType: string): string {
  if (eventType === "auth.login_failed" || eventType === "model.activation_failed") {
    return "bg-red-100 text-red-700";
  }
  if (eventType.startsWith("auth.")) return "bg-blue-100 text-blue-700";
  if (eventType.startsWith("model.")) return "bg-purple-100 text-purple-700";
  if (eventType.startsWith("device.")) return "bg-yellow-100 text-yellow-700";
  if (eventType.startsWith("chat.")) return "bg-green-100 text-green-700";
  if (eventType.startsWith("admin.")) return "bg-gray-100 text-gray-700";
  return "bg-white/10 text-sand/60";
}

function ActivityLogsTab() {
  const { token } = useAuth();
  const [items, setItems] = useState<ActivityLogRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;
  const [category, setCategory] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(PAGE_SIZE));
    if (category) params.set("event_category", category);
    if (search) params.set("search", search);

    apiGet<LogsResponse>(`/api/logs?${params.toString()}`, token)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token, page, category, search]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function handleCategoryChange(cat: string) {
    setCategory(cat);
    setPage(1);
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSearch(searchInput);
    setPage(1);
  }

  function handleClearSearch() {
    setSearchInput("");
    setSearch("");
    setPage(1);
  }

  return (
    <div className="grid gap-4">
    {/* Controls */}
      <div className="surface flex flex-wrap items-center gap-3 p-3">
        <div className="flex gap-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              type="button"
              onClick={() => handleCategoryChange(cat.value)}
              className={` px-3 py-1.5 text-xs font-semibold transition ${category === cat.value ? "bg-sand text-canvas" : "text-sand/70 hover:bg-white/10"}`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSearchSubmit} className="ml-auto flex gap-2">
          <input
            type="text"
            placeholder="Search events, users…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="field w-52 px-3 py-1.5 text-sm"
          />
          <button
            type="submit"
            className=" bg-sand px-3 py-1.5 text-xs font-semibold text-canvas transition hover:bg-sand/80"
          >
            Search
          </button>
          {search && (
            <button
              type="button"
              onClick={handleClearSearch}
              className=" border border-white/15 px-3 py-1.5 text-xs font-semibold text-sand/70 transition hover:bg-white/10"
            >
              Clear
            </button>
          )}
        </form>
      </div>

      {/* Table */}
      <div className="surface overflow-hidden">
        {error && <p className="p-4 text-sm text-red-400">{error}</p>}
        {loading ? (
          <p className="p-6 text-center text-sm text-sand/50">Loading…</p>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-sand/50">No log entries found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/10 text-left text-xs font-semibold text-sand/60">
                  <th className="px-4 py-3 whitespace-nowrap">Timestamp</th>
                  <th className="px-4 py-3">Event</th>
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">IP</th>
                  <th className="px-4 py-3">Details</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-white/5 last:border-0 hover:bg-black/[0.02]">
                    <td className="px-4 py-2.5 text-xs text-sand/50 whitespace-nowrap font-mono">
                      {item.created_at ? new Date(item.created_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block  px-2 py-0.5 text-xs font-mono font-semibold ${eventTypeBadgeClass(item.event_type)}`}>
                        {item.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-sand/70">{item.username ?? "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-sand/50 font-mono whitespace-nowrap">{item.ip_address ?? "—"}</td>
                    <td className="max-w-xs truncate px-4 py-2.5 text-xs text-sand/60 font-mono" title={item.details ?? undefined}>
                      {item.details ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between  px-4 py-3 text-sm">
          <span className="text-sand/50">
            {total} {total === 1 ? "entry" : "entries"} · Page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page === 1}
              onClick={() => setPage((p) => p - 1)}
              className=" border border-white/15 px-3 py-1.5 text-xs font-semibold text-sand/70 transition hover:bg-white/10 disabled:opacity-40"
            >
              ← Prev
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className=" border border-white/15 px-3 py-1.5 text-xs font-semibold text-sand/70 transition hover:bg-white/10 disabled:opacity-40"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DockerLogsTab() {
  const { token } = useAuth();
  const [containers, setContainers] = useState<string[]>([]);
  const [containersError, setContainersError] = useState<string | null>(null);
  const [selectedContainer, setSelectedContainer] = useState("");
  const [tail, setTail] = useState(200);
  const [lines, setLines] = useState<string[]>([]);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [loadingContainers, setLoadingContainers] = useState(false);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function fetchContainers() {
    if (!token) return;
    setLoadingContainers(true);
    setContainersError(null);
    apiGet<DockerContainersResponse>("/api/logs/docker/containers", token)
      .then((data) => {
        setContainers(data.containers);
        setSelectedContainer((prev) => {
          if (prev && data.containers.includes(prev)) return prev;
          return data.containers[0] ?? "";
        });
      })
      .catch((e: Error) => setContainersError(e.message))
      .finally(() => setLoadingContainers(false));
  }

  function fetchLogs(container: string, tailCount: number) {
    if (!token || !container) return;
    setLoadingLogs(true);
    setLogsError(null);
    apiGet<DockerLogsResponse>(`/api/logs/docker/${encodeURIComponent(container)}?tail=${tailCount}`, token)
      .then((data) => {
        setLines(data.lines);
      })
      .catch((e: Error) => {
        setLogsError(e.message);
        setLines([]);
      })
      .finally(() => setLoadingLogs(false));
  }

  // Fetch containers whenever this tab mounts (re-fetches on each tab activation)
  useEffect(() => {
    fetchContainers();
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch logs when container or tail changes
  useEffect(() => {
    if (selectedContainer) fetchLogs(selectedContainer, tail);
  }, [selectedContainer, tail, token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-refresh
  useEffect(() => {
    if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    if (autoRefresh && selectedContainer) {
      autoRefreshRef.current = setInterval(() => {
        fetchLogs(selectedContainer, tail);
      }, 5000);
    }
    return () => {
      if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
    };
  }, [autoRefresh, selectedContainer, tail, token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom when new lines arrive
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className="grid gap-4">
      {/* Controls */}
      <div className="surface flex flex-wrap items-center gap-3 p-3">
        {containersError ? (
          <p className="text-sm text-red-600">{containersError}</p>
        ) : (
          <>
            <select
              value={selectedContainer}
              onChange={(e) => setSelectedContainer(e.target.value)}
              disabled={loadingContainers || containers.length === 0}
              className="field px-3 py-1.5 text-sm disabled:opacity-50"
            >
              {containers.length === 0 && !loadingContainers && (
                <option value="">No containers found</option>
              )}
              {containers.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>

            <select
              value={tail}
              onChange={(e) => setTail(Number(e.target.value))}
              className=" border border-white/15 bg-white/10 px-3 text-sand py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sand/30"
            >
              {TAIL_OPTIONS.map((n) => (
                <option key={n} value={n}>Last {n} lines</option>
              ))}
            </select>
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-sand/70 select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className=""
            />
            Auto-refresh (5s)
          </label>
          <button
            type="button"
            onClick={() => {
              fetchContainers();
              if (selectedContainer) fetchLogs(selectedContainer, tail);
            }}
            disabled={loadingLogs || loadingContainers}
            className=" bg-sand px-3 py-1.5 text-xs font-semibold text-canvas transition hover:bg-sand/80 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Log output */}
      <div className="surface overflow-hidden">
        {logsError ? (
          <p className="p-4 text-sm text-red-600">{logsError}</p>
        ) : loadingLogs && lines.length === 0 ? (
          <p className="p-6 text-center text-sm text-sand/50">Loading…</p>
        ) : lines.length === 0 ? (
          <p className="p-6 text-center text-sm text-sand/50">
            {selectedContainer ? "No log output." : "Select a container above."}
          </p>
        ) : (
          <div className="max-h-[600px] overflow-y-auto p-4">
            <pre className="whitespace-pre-wrap break-all font-mono text-xs text-sand/80 leading-5">
              {lines.join("\n")}
            </pre>
            <div ref={logEndRef} />
          </div>
        )}
      </div>
    </div>
  );
}

type Tab = "activity" | "docker";

export default function LogsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("activity");

  return (
    <SettingsLayout title="Logs">
      <div className="grid gap-4">
      {/* Tab switcher */}
      <div className="flex gap-1  p-1.5 w-fit">
        <button
          type="button"
          onClick={() => setActiveTab("activity")}
          className={` px-4 py-1.5 text-xs font-semibold transition ${activeTab === "activity" ? "bg-sand text-canvas" : "text-sand/70 hover:bg-white/10"}`}
        >
          Activity Logs
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("docker")}
          className={` px-4 py-1.5 text-xs font-semibold transition ${activeTab === "docker" ? "bg-sand text-canvas" : "text-sand/70 hover:bg-white/10"}`}
        >
          Docker Logs
        </button>
      </div>

      {activeTab === "activity" ? <ActivityLogsTab /> : <DockerLogsTab />}
      </div>
    </SettingsLayout>
  );
}
