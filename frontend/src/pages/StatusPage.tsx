import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { formatDeviceIdLabel } from "../lib/deviceIds";
import { AccountUsageStatusRecord, AppSettingsRecord, DeviceStatusRecord, GpuPoolRecord, StatusModelRecord, StatusResponse, TokenUsageMetricRecord, TokenUsageSummaryRecord, TopTokenUserRecord } from "../lib/records";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import Modal from "../components/ui/Modal";

const POLL_INTERVAL_MS = 5000;
const PRIMARY_MODEL_COLORS = [
  "#770088",
  "#004CFF",
  "#028121",
  "#FFEE00",
  "#FF8D00",
  "#E50000",
];
const FALLBACK_MODEL_COLORS = [
  "#5b5b5b",
  "#737373",
  "#8a8a8a",
  "#a3a3a3",
  "#bdbdbd",
  "#d4d4d4",
];

const numberFormatter = new Intl.NumberFormat();

function clampPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 0;
  }

  return Math.max(0, Math.min(100, value));
}

function formatMemory(memoryMb: number) {
  if (memoryMb >= 1024) {
    return `${(memoryMb / 1024).toFixed(1)} GB`;
  }

  return `${numberFormatter.format(memoryMb)} MB`;
}

function hasKnownMemoryCapacity(memoryTotalMb: number) {
  return memoryTotalMb > 0;
}

function getMemoryPercent(memoryUsedMb: number, memoryTotalMb: number) {
  if (!hasKnownMemoryCapacity(memoryTotalMb)) {
    return null;
  }

  return clampPercent((memoryUsedMb / memoryTotalMb) * 100);
}

function formatMemorySummary(memoryUsedMb: number, memoryTotalMb: number) {
  if (!hasKnownMemoryCapacity(memoryTotalMb)) {
    return formatMemory(memoryUsedMb);
  }

  return `${formatMemory(memoryUsedMb)} of ${formatMemory(memoryTotalMb)}`;
}

function formatCombinedMemorySummary(memoryUsedMb: number, memoryTotalMb: number, hasUnknownCapacity: boolean) {
  if (hasUnknownCapacity && !hasKnownMemoryCapacity(memoryTotalMb)) {
    return `${formatMemory(memoryUsedMb)} used across pooled GPUs`;
  }
  if (hasUnknownCapacity) {
    return `${formatMemory(memoryUsedMb)} used of at least ${formatMemory(memoryTotalMb)}`;
  }

  return formatMemorySummary(memoryUsedMb, memoryTotalMb);
}

function formatDiskSpace(bytes: number) {
  if (bytes >= 1024 * 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024 * 1024 * 1024)).toFixed(1)} TB`;
  }
  if (bytes >= 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
}

function colorForModel(index: number) {
  if (index < PRIMARY_MODEL_COLORS.length) {
    return PRIMARY_MODEL_COLORS[index];
  }

  return FALLBACK_MODEL_COLORS[(index - PRIMARY_MODEL_COLORS.length) % FALLBACK_MODEL_COLORS.length];
}

function getModelColor(modelColors: Map<number, string>, modelId: number) {
  return modelColors.get(modelId) ?? FALLBACK_MODEL_COLORS[0];
}

function formatModelMemoryTooltip(model: StatusModelRecord) {
  if (model.display_memory_used_mb !== model.memory_used_mb) {
    return `${model.alias}: ${formatMemory(model.display_memory_used_mb)} attributed on this GPU (${formatMemory(model.memory_used_mb)} reported directly)`;
  }

  return `${model.alias}: ${formatMemory(model.display_memory_used_mb)}`;
}

function formatRawModelMemoryTooltip(model: StatusModelRecord) {
  return `${model.alias}: ${formatMemory(model.memory_used_mb)}`;
}

function formatTokenTooltip(metric: TokenUsageMetricRecord | TopTokenUserRecord) {
  if (!metric) {
    return undefined;
  }

  return `${numberFormatter.format(metric.input_tokens)} input / ${numberFormatter.format(metric.output_tokens)} output`;
}

function formatTokenValue(metric: TokenUsageMetricRecord | TopTokenUserRecord) {
  if (!metric) {
    return "N/A";
  }

  return numberFormatter.format(metric.total_tokens);
}

function formatWholePercent(value: number) {
  return `${Math.round(clampPercent(value))}%`;
}

function formatResetIn(seconds: number | null) {
  if (seconds === null || seconds < 0) return null;
  const days = Math.floor(seconds / (60 * 60 * 24));
  if (days > 0) {
    const remainingHours = Math.floor((seconds % (60 * 60 * 24)) / (60 * 60));
    if (remainingHours > 0) {
      return `${days} day${days !== 1 ? "s" : ""}, ${remainingHours} hour${remainingHours !== 1 ? "s" : ""}`;
    }
    return `${days} day${days !== 1 ? "s" : ""}`;
  }
  const hours = Math.floor(seconds / (60 * 60));
  if (hours > 0) {
    const remainingMinutes = Math.floor((seconds % (60 * 60)) / 60);
    if (remainingMinutes > 0) {
      return `${hours} hour${hours !== 1 ? "s" : ""}, ${remainingMinutes} minute${remainingMinutes !== 1 ? "s" : ""}`;
    }
    return `${hours} hour${hours !== 1 ? "s" : ""}`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes > 0) {
    return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
  }
  return null;
}

function getSystemHealth(activeModels: number, memoryUsagePercent: number | null) {
  if (activeModels === 0) {
    return {
      label: "Unready",
      iconClassName: "bi bi-x-octagon-fill",
      iconColorClassName: "text-[#c63f3f]",
      detail: "No models are currently loaded",
    };
  }

  if (memoryUsagePercent !== null && memoryUsagePercent > 90) {
    return {
      label: "Ready",
      iconClassName: "bi bi-exclamation-triangle-fill",
      iconColorClassName: "text-[#c98a13]",
      detail: "AI memory usage is above 90%",
    };
  }

  return {
    label: "Ready",
    iconClassName: "bi bi-check-circle-fill",
    iconColorClassName: "text-[#2f8f4e]",
    detail: "Everything is awesome! *wags*",
  };
}

function DeviceCard({ device, poolName, modelColors }: { device: DeviceStatusRecord; poolName: string | null; modelColors: Map<number, string> }) {
  const isCpuDevice = device.device_type.toLowerCase() === "cpu" || device.vendor.toLowerCase() === "cpu";
  const isPooled = poolName !== null;
  const gpuUsagePercent = clampPercent(device.gpu_usage_percent);
  const hasGpuUsage = device.gpu_usage_percent !== null && device.gpu_usage_percent !== undefined;
  const cpuUsagePercent = clampPercent(device.usage_percent);
  const hasCpuUsage = device.usage_percent !== null && device.usage_percent !== undefined;
  const memoryPercent = getMemoryPercent(device.memory_used_mb, device.memory_total_mb);
  const modelMemoryTotal = device.models.reduce(
    (sum, model) => sum + (isCpuDevice ? model.memory_used_mb : model.display_memory_used_mb),
    0,
  );
  const assignedMemoryPercent = getMemoryPercent(modelMemoryTotal, device.memory_total_mb);
  const unassignedMemoryPercent = memoryPercent !== null && assignedMemoryPercent !== null
    ? clampPercent(memoryPercent - assignedMemoryPercent)
    : 0;
  const memoryBarSegments = memoryPercent !== null ? [
    ...(isCpuDevice && unassignedMemoryPercent > 0 ? [{
      key: `${device.id}-memory-system`,
      width: unassignedMemoryPercent,
      backgroundColor: "#000000",
      title: "System RAM used outside LmPanel",
    }] : []),
    ...device.models.map((model) => ({
      key: `${device.id}-memory-${model.model_id}`,
      width: getMemoryPercent(isCpuDevice ? model.memory_used_mb : model.display_memory_used_mb, device.memory_total_mb) ?? 0,
      backgroundColor: getModelColor(modelColors, model.model_id),
      title: isCpuDevice ? formatRawModelMemoryTooltip(model) : formatModelMemoryTooltip(model),
    })).filter((segment) => segment.width > 0),
    ...(!isCpuDevice && unassignedMemoryPercent > 0 ? [{
      key: `${device.id}-memory-unassigned`,
      width: unassignedMemoryPercent,
      backgroundColor: "rgba(0, 0, 0, 0.2)",
      title: "Used by runtime or system overhead",
    }] : []),
  ] : [];

  return (
    <article className="overflow-hidden -[28px] border border-black/10 bg-white/80 p-5 shadow-sm backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-display text-xl text-ink">{device.name}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <span className=" border border-amber-200 bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">{device.display_suffix}</span>
          {isPooled && (
            <span className=" border border-violet-200 bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-700">Pooled: {poolName}</span>
          )}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {!isCpuDevice && (
          <div className="flex items-baseline justify-between border-b border-black/5 pb-1">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">GPU</p>
            <p className="text-lg font-display text-ink">{hasGpuUsage ? `${formatWholePercent(gpuUsagePercent)}` : "N/A"}</p>
          </div>
        )}

        {isCpuDevice && hasCpuUsage && (
          <div className="flex items-baseline justify-between border-b border-black/5 pb-1">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">CPU</p>
            <p className="text-lg font-display text-ink">{formatWholePercent(cpuUsagePercent)}</p>
          </div>
        )}

        <div className="flex items-baseline justify-between border-b border-black/5 pb-1">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">Memory</p>
          <p className="text-lg font-display text-ink">{formatMemorySummary(device.memory_used_mb, device.memory_total_mb)}</p>
        </div>

        {device.models.length > 0 && (
          <div className="space-y-2">
            {device.models.map((model) => (
              <div key={`${device.id}-legend-${model.model_id}`} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 shrink-0 " style={{ backgroundColor: getModelColor(modelColors, model.model_id) }} />
                <span className="text-sm font-semibold text-ink">{model.alias}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function StatusPage() {
  const { token, user } = useAuth();
  const { showError } = useToast();
  const [devices, setDevices] = useState<DeviceStatusRecord[]>([]);
  const [pools, setPools] = useState<GpuPoolRecord[]>([]);
  const [systemCpuUsagePercent, setSystemCpuUsagePercent] = useState<number | null>(null);
  const [systemDiskFreeBytes, setSystemDiskFreeBytes] = useState<number>(0);
  const [tokenUsage, setTokenUsage] = useState<TokenUsageSummaryRecord | null>(null);
  const [accountUsage, setAccountUsage] = useState<AccountUsageStatusRecord | null>(null);
  const [appSettings, setAppSettings] = useState<AppSettingsRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const lastErrorMessageRef = useRef<string | null>(null);
  const [isManageCostOpen, setIsManageCostOpen] = useState(false);
  const [modalDraft, setModalDraft] = useState({ input_price_per_1m: "0", output_price_per_1m: "0" });
  const [isSavingCost, setIsSavingCost] = useState(false);
  const [isTokenStatsOpen, setIsTokenStatsOpen] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function loadStatus(showSpinner: boolean) {
      if (showSpinner) {
        setIsLoading(true);
      }

      try {
        const response = await apiGet<StatusResponse>("/api/status", token || undefined);
        if (!isMounted) {
          return;
        }
        setDevices(response.devices);
        setSystemCpuUsagePercent(response.system_cpu_usage_percent);
        setSystemDiskFreeBytes(response.system_disk_free_bytes);
        setTokenUsage(response.token_usage);
        setAccountUsage(response.account_usage ?? null);
        lastErrorMessageRef.current = null;
      } catch (error) {
        if (!isMounted) {
          return;
        }
        setSystemCpuUsagePercent(null);
        setSystemDiskFreeBytes(0);
        setTokenUsage(null);
        setAccountUsage(null);
        const message = error instanceof Error ? error.message : "Failed to load status";
        if (lastErrorMessageRef.current !== message) {
          showError(message, { id: "status-error" });
          lastErrorMessageRef.current = message;
        }
      } finally {
        if (!isMounted) {
          return;
        }
        setIsLoading(false);
      }
    }

    void loadStatus(true);
    const intervalId = window.setInterval(() => {
      void loadStatus(false);
    }, POLL_INTERVAL_MS);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, [token]);

  useEffect(() => {
    if (!token) {
      return;
    }
    apiGet<GpuPoolRecord[]>("/api/devices/pools", token).then(setPools).catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!token) {
      return;
    }
    apiGet<AppSettingsRecord>("/api/admin/settings", token).then(setAppSettings).catch(() => {});
  }, [token]);

  const estimatedSavings = useMemo(() => {
    if (!tokenUsage || !appSettings) {
      return 0;
    }
    const forever = tokenUsage.forever;
    if (!forever) {
      return 0;
    }
    const inputCost = (forever.input_tokens / 1_000_000) * (appSettings.input_price_per_1m || 0);
    const outputCost = (forever.output_tokens / 1_000_000) * (appSettings.output_price_per_1m || 0);
    return inputCost + outputCost;
  }, [tokenUsage, appSettings]);

  function openManageCostModal() {
    setModalDraft({
      input_price_per_1m: (appSettings?.input_price_per_1m ?? 0).toString(),
      output_price_per_1m: (appSettings?.output_price_per_1m ?? 0).toString(),
    });
    setIsManageCostOpen(true);
  }

  async function saveCostSettings() {
    if (!token) return;
    setIsSavingCost(true);
    try {
      const response = await apiPatch<Record<string, unknown>, AppSettingsRecord>(
        "/api/admin/settings",
        {
          input_price_per_1m: parseFloat(modalDraft.input_price_per_1m) || 0,
          output_price_per_1m: parseFloat(modalDraft.output_price_per_1m) || 0,
        },
        token,
      );
      setAppSettings(response);
      setIsManageCostOpen(false);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save cost settings");
    } finally {
      setIsSavingCost(false);
    }
  }

  const visibleDevices = useMemo(() => devices.filter((device) => device.enabled), [devices]);
  const poolNamesByDeviceId = useMemo(() => {
    const entries = new Map<number, string>();
    for (const pool of pools) {
      for (const device of pool.devices) {
        entries.set(device.id, pool.name);
      }
    }
    return entries;
  }, [pools]);
  const visiblePoolSummaries = useMemo(() => {
    const visibleById = new Map(visibleDevices.map((device) => [device.id, device]));
    return pools
      .map((pool) => {
        const members = pool.devices
          .map((poolDevice) => visibleById.get(poolDevice.id))
          .filter((device): device is DeviceStatusRecord => Boolean(device));
        if (members.length === 0) {
          return null;
        }

        const memoryTotalMb = members.reduce((sum, device) => sum + Math.max(0, device.memory_total_mb), 0);
        const memoryUsedMb = members.reduce((sum, device) => sum + Math.max(0, device.memory_used_mb), 0);
        const hasUnknownCapacity = members.some((device) => device.memory_total_mb <= 0);
        const memberLabel = members.map((device) => `${device.name} ${device.display_suffix}`).join(", ");
        const loadedModels = Array.from(new Set(members.flatMap((device) => device.models.map((model) => model.alias)))).sort();

        return {
          id: pool.id,
          name: pool.name,
          vendor: pool.vendor,
          members,
          memberLabel,
          memoryTotalMb,
          memoryUsedMb,
          hasUnknownCapacity,
          memoryPercent: hasUnknownCapacity ? null : getMemoryPercent(memoryUsedMb, memoryTotalMb),
          loadedModels,
        };
      })
      .filter((pool): pool is NonNullable<typeof pool> => pool !== null);
  }, [pools, visibleDevices]);
  const modelColors = useMemo(() => {
    const modelIds = Array.from(new Set(visibleDevices.flatMap((device) => device.models.map((model) => model.model_id)))).sort((left, right) => left - right);
    return new Map(modelIds.map((modelId, index) => [modelId, colorForModel(index)]));
  }, [visibleDevices]);

  const summary = useMemo(() => {
    const activeModels = visibleDevices.reduce((sum, device) => sum + device.models.length, 0);
    const totalMemory = visibleDevices.reduce((sum, device) => sum + device.memory_total_mb, 0);
    const usedMemory = visibleDevices.reduce((sum, device) => sum + device.memory_used_mb, 0);
    const hasKnownTotalMemory = totalMemory > 0;
    const memoryUsagePercent = hasKnownTotalMemory ? getMemoryPercent(usedMemory, totalMemory) : null;

    return {
      onlineDevices: visibleDevices.length,
      activeModels,
      totalMemory,
      usedMemory,
      memoryUsagePercent,
    };
  }, [visibleDevices]);

  const tokenCards = useMemo(() => {
    const emptyMetric: TokenUsageMetricRecord = { total_tokens: 0, input_tokens: 0, output_tokens: 0 };
    const summary = tokenUsage;
    const topUserLast24Hours = summary?.top_user_last_24_hours ?? null;
    const last24HoursTotalTokens = summary?.last_24_hours.total_tokens ?? 0;
    const topUserLast24HoursPercent = topUserLast24Hours && last24HoursTotalTokens > 0
      ? (topUserLast24Hours.total_tokens / last24HoursTotalTokens) * 100
      : 0;

    return [
      {
        label: "Since Startup",
        value: formatTokenValue(summary?.since_startup ?? emptyMetric),
        title: formatTokenTooltip(summary?.since_startup ?? emptyMetric),
        detail: "Tokens",
        className: "lg:col-span-3",
      },
      {
        label: "Last 60 Minutes",
        value: formatTokenValue(summary?.last_1_hour ?? emptyMetric),
        title: formatTokenTooltip(summary?.last_1_hour ?? emptyMetric),
        detail: "Tokens",
        className: "lg:col-span-3",
      },
      {
        label: "Last 24 Hours",
        value: formatTokenValue(summary?.last_24_hours ?? emptyMetric),
        title: formatTokenTooltip(summary?.last_24_hours ?? emptyMetric),
        detail: "Tokens",
        className: "lg:col-span-3",
      },
      {
        label: "Last 7 Days",
        value: formatTokenValue(summary?.last_7_days ?? emptyMetric),
        title: formatTokenTooltip(summary?.last_7_days ?? emptyMetric),
        detail: "Tokens",
        className: "lg:col-span-3",
      },
      {
        label: "Last 30 Days",
        value: formatTokenValue(summary?.last_30_days ?? emptyMetric),
        title: formatTokenTooltip(summary?.last_30_days ?? emptyMetric),
        detail: "Tokens",
        className: "lg:col-span-3",
      },
      {
        label: "Forever",
        value: formatTokenValue(summary?.forever ?? emptyMetric),
        title: formatTokenTooltip(summary?.forever ?? emptyMetric),
        detail: "Tokens",
        className: "lg:col-span-3",
      },
      {
        label: "Top User 24h",
        value: token ? (topUserLast24Hours?.username ?? "N/A") : "N/A",
        title: token ? formatTokenTooltip(topUserLast24Hours) : undefined,
        detail: token ? (topUserLast24Hours ? formatWholePercent(topUserLast24HoursPercent) : "0%") : "Log in to view",
        className: "lg:col-span-3",
      },
    ];
  }, [tokenUsage]);

  const systemHealth = useMemo(
    () => getSystemHealth(summary.activeModels, summary.memoryUsagePercent),
    [summary.activeModels, summary.memoryUsagePercent],
  );

  return (
    <section className="grid gap-4 overflow-hidden -[32px] border border-black/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.88)_0%,rgba(245,240,226,0.78)_100%)] p-6 shadow-sm backdrop-blur">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-12">
          <div className=" border border-black/10 bg-white/80 p-4 lg:col-span-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">System Health</p>
            <div className="mt-2 flex items-center gap-3">
              <i className={`${systemHealth.iconClassName} ${systemHealth.iconColorClassName} text-[28px] leading-none`} aria-hidden="true" />
              <p className="font-display text-3xl text-ink">{systemHealth.label}</p>
            </div>
            <p className="mt-1 text-sm text-black/55">{systemHealth.detail}</p>
          </div>

          <div className=" border border-black/10 bg-white/80 p-4 lg:col-span-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">Free Disk Space</p>
            <p className="mt-2 font-display text-3xl text-ink">{formatDiskSpace(systemDiskFreeBytes)}</p>
            <p className="mt-1 text-sm text-black/55">Available on /</p>
          </div>

          <div className=" border border-black/10 bg-white/80 p-4 lg:col-span-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">Host CPU</p>
            <p className="mt-2 font-display text-3xl text-ink">{systemCpuUsagePercent !== null ? `${systemCpuUsagePercent.toFixed(1)}%` : "N/A"}</p>
            <p className="mt-1 text-sm text-black/55">Total utilization</p>
          </div>

          <div className=" border border-black/10 bg-white/80 p-4 lg:col-span-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">AI Memory</p>
            <p className="mt-2 font-display text-3xl text-ink">{summary.memoryUsagePercent !== null ? `${summary.memoryUsagePercent.toFixed(1)}%` : "N/A"}</p>
            <p className="mt-1 text-sm text-black/55">{formatMemorySummary(summary.usedMemory, summary.totalMemory)}</p>
          </div>

          <button
            type="button"
            onClick={() => setIsTokenStatsOpen(!isTokenStatsOpen)}
            className="flex w-full items-center justify-between  border border-black/10 bg-white/80 p-4 text-left hover:bg-white/90 lg:col-span-12"
          >
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">Token Usage</p>
            <i className={`bi bi-chevron-down text-lg text-black/40 transition-transform ${isTokenStatsOpen ? "rotate-180" : ""}`} aria-hidden="true" />
          </button>

          {isTokenStatsOpen && tokenCards.map((card) => (
            <div key={card.label} className={` border border-black/10 bg-white/80 p-4 ${card.className}`}>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">{card.label}</p>
              <p className="mt-2 font-display text-3xl text-ink" title={card.title}>{card.value}</p>
              <p className="mt-1 text-sm text-black/55">{card.detail}</p>
            </div>
          ))}

          {isTokenStatsOpen && (
            <div className=" border border-black/10 bg-white/80 p-4 lg:col-span-3">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-black/45">Estimated Savings</p>
              <p className="mt-2 font-display text-3xl text-ink">{appSettings ? `$${estimatedSavings.toFixed(2)}` : "N/A"}</p>
              {user?.is_admin ? (
                <p className="mt-1 text-sm">
                  <a href="#" className="text-blue-600 hover:underline" onClick={(e) => { e.preventDefault(); openManageCostModal(); }}>Manage Cost</a>
                </p>
              ) : appSettings ? (
                <p className="mt-1 text-sm text-black/55">Based on cloud API pricing of ${appSettings.input_price_per_1m.toFixed(2)}/1M Input, ${appSettings.output_price_per_1m.toFixed(2)}/1M Output</p>
              ) : (
                <p className="mt-1 text-sm text-black/55">Log in to view</p>
              )}
            </div>
          )}
        </div>

      {user?.is_admin && (
        <Modal open={isManageCostOpen} onClose={() => setIsManageCostOpen(false)} labelledBy="manage-cost-modal-title" panelClassName="max-w-lg">
        <div className="p-6">
          <h2 id="manage-cost-modal-title" className="font-display text-2xl text-ink">Manage Cost</h2>
          <p className="mt-1 text-sm text-black/55">Set the price per 1M tokens for input and output to estimate your savings.</p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="input-price" className="block text-sm font-medium text-black/70">Input (per 1M tokens)</label>
              <div className="mt-1 flex  border border-black/10 bg-white overflow-hidden">
                <span className="flex items-center pl-3 text-black/50">$</span>
                <input
                  id="input-price"
                  type="number"
                  step="0.000001"
                  min="0"
                  value={modalDraft.input_price_per_1m}
                  onChange={(e) => setModalDraft((d) => ({ ...d, input_price_per_1m: e.target.value }))}
                  className="w-full border-0 bg-transparent px-3 py-2.5 text-ink outline-none focus:ring-0"
                />
              </div>
            </div>

            <div>
              <label htmlFor="output-price" className="block text-sm font-medium text-black/70">Output (per 1M tokens)</label>
              <div className="mt-1 flex  border border-black/10 bg-white overflow-hidden">
                <span className="flex items-center pl-3 text-black/50">$</span>
                <input
                  id="output-price"
                  type="number"
                  step="0.000001"
                  min="0"
                  value={modalDraft.output_price_per_1m}
                  onChange={(e) => setModalDraft((d) => ({ ...d, output_price_per_1m: e.target.value }))}
                  className="w-full border-0 bg-transparent px-3 py-2.5 text-ink outline-none focus:ring-0"
                />
              </div>
            </div>
          </div>

          <div className="mt-6 flex justify-end">
            <button
              type="button"
              onClick={saveCostSettings}
              disabled={isSavingCost}
              className=" bg-black px-4 py-2 text-sm font-medium text-white hover:bg-black/85 disabled:opacity-50"
            >
              {isSavingCost ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </Modal>
      )}

      {isLoading ? (
        <div className=" border border-black/10 bg-white/80 px-4 py-8 text-sm text-black/55 shadow-sm">Loading...</div>
      ) : visibleDevices.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {visibleDevices.map((device) => <DeviceCard key={device.id} device={device} poolName={poolNamesByDeviceId.get(device.id) ?? null} modelColors={modelColors} />)}
        </div>
      ) : (
        <div className=" border border-dashed border-black/15 bg-white/60 px-4 py-8 text-sm text-black/55 shadow-sm">No ready devices are available.</div>
      )}
    </section>
  );
}