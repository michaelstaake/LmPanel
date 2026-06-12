import { useEffect, useMemo, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import Modal from "../components/ui/Modal";
import { formatDeviceIdLabel } from "../lib/deviceIds";
import { DeviceRecord, DeviceUpdateResponse, GpuPoolRecord } from "../lib/records";

const AUTO_SAVE_DELAY_MS = 700;
const POOL_VENDORS = ["nvidia", "vulkan", "rocm"] as const;
const SPLIT_MODES = ["layer", "tensor"] as const;

function normalizePoolSplitMode(mode: string): (typeof SPLIT_MODES)[number] {
  return mode === "tensor" ? "tensor" : "layer";
}

function splitModeLabel(mode: string) {
  if (mode === "layer" || mode === "row") return "Layer";
  if (mode === "tensor") return "Tensor";
  return mode;
}

function splitModeDescription(mode: string) {
  if (mode === "layer") return "Default for multi-GPU pools. Splits the model by layer across pool members.";
  if (mode === "tensor") return "Experimental. May improve token speed on fast GPU interconnects; try layer first.";
  return "";
}

function deviceTypeLabel(device: { vendor: string; device_type: string }) {
  if (device.vendor === "cpu" && device.device_type === "cpu") return "CPU";
  return `${vendorLabel(device.vendor).toUpperCase()} ${device.device_type.toUpperCase()}`;
}

function buildDevicePayload(device: DeviceRecord) {
  return {
    name: device.name,
    enabled: device.enabled,
    priority: device.priority,
    max_threads: device.max_threads,
    max_slots: device.max_slots,
  };
}

function serializeDevice(device: DeviceRecord) {
  return JSON.stringify(buildDevicePayload(device));
}

function sortPools(pools: GpuPoolRecord[]) {
  return [...pools].sort((left, right) => left.vendor.localeCompare(right.vendor) || left.name.localeCompare(right.name) || left.id - right.id);
}

function vendorLabel(vendor: string) {
  if (vendor === "nvidia") return "NVIDIA";
  if (vendor === "vulkan") return "Vulkan";
  if (vendor === "rocm") return "ROCm";
  return vendor;
}

function parseNonNegativeInput(value: string) {
  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    return 0;
  }

  return Math.max(0, parsed);
}

type DevicesPageProps = {
  setupMode?: boolean;
  onContinue?: () => void;
};

export default function DevicesPage({ setupMode = false, onContinue }: DevicesPageProps) {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [savingDeviceIds, setSavingDeviceIds] = useState<number[]>([]);
  const [pendingDeviceIds, setPendingDeviceIds] = useState<number[]>([]);
  const latestDevicesRef = useRef<DeviceRecord[]>([]);
  const savedSnapshotsRef = useRef<Record<number, string>>({});
  const saveTimeoutsRef = useRef<Record<number, number>>({});
  const savingIdsRef = useRef<Set<number>>(new Set());
  const resaveRequestedRef = useRef<Set<number>>(new Set());

  const [pools, setPools] = useState<GpuPoolRecord[]>([]);
  const [poolLoadingTarget, setPoolLoadingTarget] = useState<string | null>(null);
  const [selectedPoolDeviceIds, setSelectedPoolDeviceIds] = useState<number[]>([]);
  const [poolDraftName, setPoolDraftName] = useState("GPU Pool");
  const [poolDraftVendor, setPoolDraftVendor] = useState<(typeof POOL_VENDORS)[number]>("nvidia");
  const [poolDraftSplitMode, setPoolDraftSplitMode] = useState<(typeof SPLIT_MODES)[number]>("layer");
  const [editingPoolId, setEditingPoolId] = useState<number | null>(null);
  const [isPoolModalOpen, setIsPoolModalOpen] = useState(false);
  const [showDeletePoolConfirmId, setShowDeletePoolConfirmId] = useState<number | null>(null);
  const [draggedDeviceId, setDraggedDeviceId] = useState<number | null>(null);
  const [isReordering, setIsReordering] = useState(false);

  // Device settings modal state
  const [editingDeviceId, setEditingDeviceId] = useState<number | null>(null);
  const [deviceModalDraft, setDeviceModalDraft] = useState<DeviceRecord | null>(null);
  const [isDeviceModalOpen, setIsDeviceModalOpen] = useState(false);

  useEffect(() => {
    latestDevicesRef.current = devices;
  }, [devices]);

  useEffect(() => {
    if (!token) {
      return;
    }
    void refreshDevices(token);
    void refreshPools(token);
  }, [token]);

  async function refreshDevices(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<DeviceRecord[]>("/api/devices", activeToken);
      savedSnapshotsRef.current = Object.fromEntries(response.map((device) => [device.id, serializeDevice(device)]));
      setDevices(response);
      setPendingDeviceIds([]);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load devices", { id: "devices-error" });
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshPools(activeToken: string) {
    try {
      const response = await apiGet<GpuPoolRecord[]>("/api/devices/pools", activeToken);
      setPools(sortPools(response));
    } catch {
      // pool endpoint errors are non-fatal
    }
  }

  function sortDevices(devices: DeviceRecord[]) {
    return [...devices].sort((left, right) => left.priority - right.priority || left.id - right.id);
  }

  function moveDevices(devices: DeviceRecord[], fromIndex: number, toIndex: number) {
    const nextDevices = [...devices];
    const [movedDevice] = nextDevices.splice(fromIndex, 1);
    nextDevices.splice(toIndex, 0, movedDevice);
    return nextDevices.map((device, index) => ({ ...device, priority: index }));
  }

  function handleDragStart(event: DragEvent<HTMLElement>, deviceId: number) {
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") {
      event.preventDefault();
      return;
    }
    setDraggedDeviceId(deviceId);
  }

  function handleDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault();
  }

  function handleDragEnd() {
    setDraggedDeviceId(null);
  }

  async function handleDeviceDrop(targetDeviceId: number) {
    if (draggedDeviceId === null || draggedDeviceId === targetDeviceId || isReordering) {
      setDraggedDeviceId(null);
      return;
    }
    const sorted = sortDevices(devices);
    const fromIndex = sorted.findIndex((device) => device.id === draggedDeviceId);
    const toIndex = sorted.findIndex((device) => device.id === targetDeviceId);
    if (fromIndex === -1 || toIndex === -1) {
      setDraggedDeviceId(null);
      return;
    }
    const previousDevices = devices;
    const nextDevices = moveDevices(sorted, fromIndex, toIndex);
    setDraggedDeviceId(null);
    setDevices(nextDevices);
    if (!token) {
      return;
    }
    setIsReordering(true);
    try {
      await apiPost<{ devices: { id: number; priority: number }[] }, { status: string }>(
        "/api/devices/reorder",
        {
          devices: nextDevices.map((device, index) => ({ id: device.id, priority: index })),
        },
        token,
      );
      showSuccess("Saved device order.", { id: "devices-success" });
    } catch (error) {
      setDevices(previousDevices);
      showError(error instanceof Error ? error.message : "Failed to save device order", { id: "devices-error" });
    } finally {
      setIsReordering(false);
    }
  }

  useEffect(() => () => {
    Object.values(saveTimeoutsRef.current).forEach((timeoutId) => window.clearTimeout(timeoutId));
  }, []);

  function scheduleDeviceSave(deviceId: number) {
    const existingTimeout = saveTimeoutsRef.current[deviceId];
    if (existingTimeout) {
      window.clearTimeout(existingTimeout);
    }

    setPendingDeviceIds((current) => (current.includes(deviceId) ? current : [...current, deviceId]));

    saveTimeoutsRef.current[deviceId] = window.setTimeout(() => {
      delete saveTimeoutsRef.current[deviceId];
      void persistDevice(deviceId);
    }, AUTO_SAVE_DELAY_MS);
  }

  function updateDeviceDraft(deviceId: number, updates: Partial<DeviceRecord>) {
    setDevices((current) => current.map((device) => (device.id === deviceId ? { ...device, ...updates } : device)));
    scheduleDeviceSave(deviceId);
  }

  function commitDeviceName(deviceId: number) {
    const device = latestDevicesRef.current.find((item) => item.id === deviceId);
    if (!device) {
      return;
    }

    const normalized = device.name.trim() || device.default_name || device.name;
    if (normalized === device.name) {
      return;
    }

    updateDeviceDraft(deviceId, { name: normalized });
  }

  async function persistDevice(deviceId: number) {
    if (!token) {
      return;
    }

    if (savingIdsRef.current.has(deviceId)) {
      resaveRequestedRef.current.add(deviceId);
      return;
    }

    const device = latestDevicesRef.current.find((item) => item.id === deviceId);
    if (!device) {
      return;
    }

    if (savedSnapshotsRef.current[deviceId] === serializeDevice(device)) {
      setPendingDeviceIds((current) => current.filter((id) => id !== deviceId));
      return;
    }

    savingIdsRef.current.add(deviceId);
    setSavingDeviceIds((current) => (current.includes(deviceId) ? current : [...current, deviceId]));
    setPendingDeviceIds((current) => current.filter((id) => id !== deviceId));

    let savedSuccessfully = false;

    try {
      const response = await apiPatch<Record<string, string | number | boolean>, DeviceUpdateResponse>(`/api/devices/${device.id}`, {
        ...buildDevicePayload(device),
      }, token);
      savedSnapshotsRef.current[device.id] = serializeDevice(response.device);
      setDevices((current) => current.map((item) => (item.id === device.id ? response.device : item)));
      showSuccess(`Saved device settings for ${response.device.name}.`, { id: "devices-success" });
      savedSuccessfully = true;
    } catch (error) {
      showError(error instanceof Error ? error.message : "Device update failed", { id: "devices-error" });
    } finally {
      savingIdsRef.current.delete(deviceId);
      setSavingDeviceIds((current) => current.filter((id) => id !== deviceId));

      const latestDevice = latestDevicesRef.current.find((item) => item.id === deviceId);
      const needsResave = savedSuccessfully && latestDevice && savedSnapshotsRef.current[deviceId] !== serializeDevice(latestDevice);
      const shouldResave = resaveRequestedRef.current.has(deviceId) || Boolean(needsResave);
      resaveRequestedRef.current.delete(deviceId);

      if (shouldResave) {
        scheduleDeviceSave(deviceId);
      }
    }
  }

  const enabledDevices = devices.filter((device) => device.enabled).length;
  const availablePoolVendors = useMemo(
    () => POOL_VENDORS.filter((vendor) => devices.filter((device) => device.vendor === vendor).length > 1),
    [devices],
  );
  const draftVendorOptions = useMemo(() => {
    const currentVendor = editingPoolId === null ? null : pools.find((pool) => pool.id === editingPoolId)?.vendor ?? null;
    return Array.from(new Set([...(currentVendor ? [currentVendor] : []), ...availablePoolVendors]));
  }, [availablePoolVendors, editingPoolId, pools]);
  const showPoolSection = !setupMode && availablePoolVendors.length > 0;
  const poolDeviceToPool = useMemo(() => {
    const mapping = new Map<number, GpuPoolRecord>();
    for (const pool of pools) {
      for (const device of pool.devices) {
        mapping.set(device.id, pool);
      }
    }
    return mapping;
  }, [pools]);
  const editablePool = editingPoolId === null ? null : pools.find((pool) => pool.id === editingPoolId) ?? null;
  const filteredDraftDevices = useMemo(
    () => devices.filter((device) => {
      if (device.vendor !== poolDraftVendor) {
        return false;
      }
      const owningPool = poolDeviceToPool.get(device.id);
      return !owningPool || owningPool.id === editingPoolId;
    }),
    [devices, editingPoolId, poolDeviceToPool, poolDraftVendor],
  );

  useEffect(() => {
    if (draftVendorOptions.length === 0) {
      return;
    }
    if (!draftVendorOptions.includes(poolDraftVendor)) {
      setPoolDraftVendor(draftVendorOptions[0] as (typeof POOL_VENDORS)[number]);
    }
  }, [draftVendorOptions, poolDraftVendor]);

  useEffect(() => {
    setSelectedPoolDeviceIds((current) => current.filter((deviceId) => filteredDraftDevices.some((device) => device.id === deviceId)));
  }, [filteredDraftDevices]);

  function resetPoolDraft() {
    setEditingPoolId(null);
    setPoolDraftName("GPU Pool");
    setPoolDraftVendor((draftVendorOptions[0] ?? availablePoolVendors[0] ?? "nvidia") as (typeof POOL_VENDORS)[number]);
    setPoolDraftSplitMode("layer");
    setSelectedPoolDeviceIds([]);
    setShowDeletePoolConfirmId(null);
  }

  function closePoolModal() {
    setIsPoolModalOpen(false);
    resetPoolDraft();
  }

  function openNewPoolModal() {
    resetPoolDraft();
    setIsPoolModalOpen(true);
  }

  function startEditingPool(pool: GpuPoolRecord) {
    setEditingPoolId(pool.id);
    setPoolDraftName(pool.name);
    setPoolDraftVendor(pool.vendor as (typeof POOL_VENDORS)[number]);
    setPoolDraftSplitMode(normalizePoolSplitMode(pool.split_mode));
    setSelectedPoolDeviceIds(pool.devices.map((device) => device.id));
    setIsPoolModalOpen(true);
    setShowDeletePoolConfirmId(null);
  }

  function togglePoolDevice(deviceId: number) {
    setSelectedPoolDeviceIds((current) =>
      current.includes(deviceId) ? current.filter((id) => id !== deviceId) : [...current, deviceId],
    );
  }

  function isPoolEnabled(pool: GpuPoolRecord) {
    return pool.devices.length > 0 && pool.devices.every((poolDevice) => devices.find((device) => device.id === poolDevice.id)?.enabled === true);
  }

  async function handleTogglePool(pool: GpuPoolRecord) {
    if (!token) return;
    const nextEnabled = !isPoolEnabled(pool);
    setPoolLoadingTarget(`toggle:${pool.id}`);
    try {
      await Promise.all(
        pool.devices.map((poolDevice) =>
          apiPatch<{ enabled: boolean }, { status: string; device: DeviceRecord }>(
            `/api/devices/${poolDevice.id}`,
            { enabled: nextEnabled },
            token,
          ),
        ),
      );
      await refreshDevices(token);
      showSuccess(`${pool.name} ${nextEnabled ? "enabled" : "disabled"}.`, { id: "devices-success" });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to toggle pool", { id: "devices-error" });
      await refreshDevices(token);
    } finally {
      setPoolLoadingTarget(null);
    }
  }

  async function handleCreatePool() {
    if (!token || selectedPoolDeviceIds.length < 2) return;
    setPoolLoadingTarget("create");
    try {
      const response = await apiPost<{ name: string; vendor: string; device_ids: number[]; split_mode: string }, { pool: GpuPoolRecord }>(
        "/api/devices/pools",
        { name: poolDraftName.trim(), vendor: poolDraftVendor, device_ids: selectedPoolDeviceIds, split_mode: poolDraftSplitMode },
        token,
      );
      setPools((current) => sortPools([...current, response.pool]));
      setIsPoolModalOpen(false);
      resetPoolDraft();
      showSuccess(`Created ${response.pool.name}.`, { id: "devices-success" });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to create GPU pool", { id: "devices-error" });
    } finally {
      setPoolLoadingTarget(null);
    }
  }

  async function handleUpdatePool() {
    if (!token || selectedPoolDeviceIds.length < 2 || !editablePool) return;
    const removedDeviceIds = editablePool.devices.map((device) => device.id).filter((id) => !selectedPoolDeviceIds.includes(id));
    setPoolLoadingTarget(`update:${editablePool.id}`);
    try {
      const response = await apiPatch<{ name: string; vendor: string; device_ids: number[]; split_mode: string }, { pool: GpuPoolRecord }>(
        `/api/devices/pools/${editablePool.id}`,
        { name: poolDraftName.trim(), vendor: poolDraftVendor, device_ids: selectedPoolDeviceIds, split_mode: poolDraftSplitMode },
        token,
      );
      if (removedDeviceIds.length > 0) {
        await Promise.all(
          removedDeviceIds.map((deviceId) =>
            apiPatch<{ enabled: boolean }, { status: string; device: DeviceRecord }>(
              `/api/devices/${deviceId}`,
              { enabled: false },
              token,
            ),
          ),
        );
      }
      setPools((current) => sortPools(current.map((pool) => (pool.id === response.pool.id ? response.pool : pool))));
      setIsPoolModalOpen(false);
      resetPoolDraft();
      await refreshDevices(token);
      showSuccess(`Updated ${response.pool.name}.`, { id: "devices-success" });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to update GPU pool", { id: "devices-error" });
    } finally {
      setPoolLoadingTarget(null);
    }
  }

  async function handleDeletePool(pool: GpuPoolRecord) {
    if (!token) return;
    const memberDeviceIds = pool.devices.map((device) => device.id);
    setPoolLoadingTarget(`delete:${pool.id}`);
    setShowDeletePoolConfirmId(null);
    try {
      await apiDelete<{ status: string }>(`/api/devices/pools/${pool.id}`, token);
      if (memberDeviceIds.length > 0) {
        await Promise.all(
          memberDeviceIds.map((deviceId) =>
            apiPatch<{ enabled: boolean }, { status: string; device: DeviceRecord }>(
              `/api/devices/${deviceId}`,
              { enabled: false },
              token,
            ),
          ),
        );
      }
      setPools((current) => current.filter((item) => item.id !== pool.id));
      if (editingPoolId === pool.id) {
        setIsPoolModalOpen(false);
        resetPoolDraft();
      }
      await refreshDevices(token);
      showSuccess(`${pool.name} deleted. Any models assigned to it have been reverted to Auto.`, { id: "devices-success" });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to delete GPU pool", { id: "devices-error" });
    } finally {
      setPoolLoadingTarget(null);
    }
  }

  function openDeviceSettingsModal(device: DeviceRecord) {
    setEditingDeviceId(device.id);
    setDeviceModalDraft({ ...device });
    setIsDeviceModalOpen(true);
  }

  function closeDeviceSettingsModal() {
    if (editingDeviceId !== null && deviceModalDraft !== null) {
      updateDeviceDraft(editingDeviceId, deviceModalDraft);
      void persistDevice(editingDeviceId);
    }
    setEditingDeviceId(null);
    setDeviceModalDraft(null);
    setIsDeviceModalOpen(false);
  }

  function handleDeviceModalSave() {
    if (editingDeviceId === null || !deviceModalDraft) return;
    updateDeviceDraft(editingDeviceId, deviceModalDraft);
    void persistDevice(editingDeviceId);
    setEditingDeviceId(null);
    setDeviceModalDraft(null);
    setIsDeviceModalOpen(false);
  }

  const editableDevice = editingDeviceId === null ? null : devices.find((d) => d.id === editingDeviceId) ?? null;

  return (
    <section className="grid gap-4">
      <article className="surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="mt-2 font-display text-xl">{setupMode ? "Step 2: Devices" : "Devices"}</h2>
            {setupMode ? <p className="mt-2 max-w-3xl text-sm text-sand/70">Enable at least one device so models have somewhere to run.</p> : null}
          </div>
        </div>
        <div className="mt-5 space-y-4">
          {showPoolSection ? (
            <article className="surface-muted border-violet-500/30 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-display text-base text-sand">GPU Pools</h3>
                  <p className="mt-1 text-sm text-sand/65">
                    Use Pools to load larger models across multiple GPUs. Once a GPU is in a Pool, it will not be available to run models independently.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={openNewPoolModal}
                  className="cursor-pointer  badge-accent px-3 py-1.5 text-xs font-semibold hover:bg-violet-500/25"
                >
                  New Pool
                </button>
              </div>

              <div className="mt-4 space-y-3">
                {pools.length === 0 ? (
                  <p className="surface-muted border border-dashed border-white/15 px-4 py-4 text-sm text-sand/60">
                    No pools currently exist. Use the New Pool button to create one!
                  </p>
                ) : (
                  pools.map((pool) => {
                    const poolEnabled = isPoolEnabled(pool);
                    return (
                      <div key={pool.id} className="surface border border-white/10 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <h4 className="font-display text-base text-sand">{pool.name}</h4>
                              <span className=" badge-accent px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.12em]">{vendorLabel(pool.vendor)}</span>
                              <span className=" badge-accent px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.12em]">{splitModeLabel(pool.split_mode)}</span>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => void handleTogglePool(pool)}
                              disabled={poolLoadingTarget !== null}
                              className={`cursor-pointer  border px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${poolEnabled ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25" : "border-white/15 bg-white/10 text-sand/55 hover:bg-white/10"}`}
                            >
                              {poolLoadingTarget === `toggle:${pool.id}` ? "Saving..." : poolEnabled ? "Enabled" : "Disabled"}
                            </button>
                            <button
                              type="button"
                              onClick={() => startEditingPool(pool)}
                              className="cursor-pointer  badge-accent px-3 py-1.5 text-xs font-semibold hover:bg-violet-500/25"
                            >
                              Settings
                            </button>
                            <button
                              type="button"
                              onClick={() => setShowDeletePoolConfirmId(pool.id)}
                              className="btn-danger cursor-pointer px-3 py-1.5 text-xs font-semibold"
                            >
                              Delete
                            </button>
                          </div>
                        </div>

                        {showDeletePoolConfirmId === pool.id ? (
                          <div className="mt-3 surface-muted border-rose-500/30 px-4 py-3">
                            <p className="text-sm text-rose-300">Delete {pool.name}? Models assigned to it will be unloaded and reverted to Auto. Pool member GPUs will be disabled.</p>
                            <div className="mt-3 flex gap-2">
                              <button type="button" onClick={() => void handleDeletePool(pool)} disabled={poolLoadingTarget !== null} className="btn-danger cursor-pointer px-3 py-1.5 text-xs font-semibold disabled:opacity-60">
                                {poolLoadingTarget === `delete:${pool.id}` ? "Deleting..." : "Confirm Delete"}
                              </button>
                              <button type="button" onClick={() => setShowDeletePoolConfirmId(null)} className="cursor-pointer  btn-secondary px-3 py-1.5 text-xs font-semibold text-sand/70 hover:bg-white/10">
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : null}

                        <ul className="mt-3 space-y-1">
                          {pool.devices.map((device) => (
                            <li key={device.id} className="text-sm text-sand">
                              {device.name} <span className="text-sand/55">· {formatDeviceIdLabel(device)} · {device.memory_mb.toLocaleString()} MB</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })
                )}
              </div>
            </article>
          ) : null}

          {showPoolSection ? (
            <Modal
              open={isPoolModalOpen}
              onClose={closePoolModal}
              labelledBy="pool-modal-title"
              describedBy="pool-modal-description"
              panelClassName="max-w-2xl"
            >
              <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 id="pool-modal-title" className="mt-2 font-display text-xl text-sand">
                      {editingPoolId === null ? "New GPU Pool" : `Edit ${editablePool?.name ?? "GPU Pool"}`}
                    </h3>
                  </div>
                  <button
                    type="button"
                    onClick={closePoolModal}
                    className="cursor-pointer  border border-white/15 bg-white/10 px-3 text-sand py-1.5 text-sm font-semibold text-sand/70 hover:bg-white/10"
                  >
                    Close
                  </button>
                </div>
              </div>

              <div className="grid gap-4 px-5 py-5 sm:px-6">
                <label className="grid gap-1 text-sm text-sand/70">
                  <span>Pool Name</span>
                  <input className=" field px-3 py-2 text-sm" value={poolDraftName} onChange={(event) => setPoolDraftName(event.target.value)} />
                </label>
                <label className="grid gap-1 text-sm text-sand/70">
                  <span>Pool Type</span>
                  <select className=" field px-3 py-2 text-sm" value={poolDraftVendor} onChange={(event) => setPoolDraftVendor(event.target.value as (typeof POOL_VENDORS)[number])}>
                    {draftVendorOptions.map((vendor) => (
                      <option key={vendor} value={vendor}>{vendorLabel(vendor)}</option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-sm text-sand/70">
                  <span>Split Mode</span>
                  <span className="text-xs text-sand/45">{splitModeDescription(poolDraftSplitMode)}</span>
                  <select className=" field px-3 py-2 text-sm" value={poolDraftSplitMode} onChange={(event) => setPoolDraftSplitMode(event.target.value as (typeof SPLIT_MODES)[number])}>
                    {SPLIT_MODES.map((mode) => (
                      <option key={mode} value={mode}>{splitModeLabel(mode)}</option>
                    ))}
                  </select>
                </label>
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-sand/50">Pool Members</p>
                  <div className="space-y-2">
                    {filteredDraftDevices.length > 0 ? filteredDraftDevices.map((device) => (
                      <label key={device.id} className="flex cursor-pointer items-center gap-3 surface-muted px-3 py-2 text-sm text-sand/80 hover:bg-white/5">
                        <input
                          type="checkbox"
                          checked={selectedPoolDeviceIds.includes(device.id)}
                          onChange={() => togglePoolDevice(device.id)}
                        />
                        <span className="flex-1">{device.name}</span>
                        <span className="text-xs text-sand/45">{formatDeviceIdLabel(device)} · {device.memory_mb.toLocaleString()} MB</span>
                      </label>
                    )) : (
                      <p className="surface-muted border border-dashed border-white/15 px-3 py-3 text-sm text-sand/60">No unassigned {vendorLabel(poolDraftVendor)} GPUs are available for this pool.</p>
                    )}
                  </div>
                </div>
                {selectedPoolDeviceIds.length < 2 ? (
                  <p className="text-xs text-sand/55">Select at least 2 {vendorLabel(poolDraftVendor)} GPUs.</p>
                ) : null}
              </div>

              <div className="flex flex-wrap justify-end gap-2 border-t border-white/10 px-5 py-4 sm:px-6">
                <button
                  type="button"
                  onClick={closePoolModal}
                  className="cursor-pointer  border border-white/15 bg-white/10 px-3 text-sand py-1.5 text-sm font-semibold text-sand/70 hover:bg-white/10"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={selectedPoolDeviceIds.length < 2 || poolLoadingTarget !== null || poolDraftName.trim().length === 0}
                  onClick={editingPoolId === null ? () => void handleCreatePool() : () => void handleUpdatePool()}
                  className="cursor-pointer bg-sand px-4 py-1.5 text-sm font-semibold text-canvas hover:bg-sand/80 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {poolLoadingTarget === "create" || (editingPoolId !== null && poolLoadingTarget === `update:${editingPoolId}`) ? "Saving..." : editingPoolId === null ? "Create Pool" : "Save Pool"}
                </button>
              </div>
            </Modal>
          ) : null}

           {isDeviceModalOpen && editingDeviceId !== null && deviceModalDraft ? (
             <Modal
               open={isDeviceModalOpen}
               onClose={closeDeviceSettingsModal}
               labelledBy="device-settings-modal-title"
               panelClassName="w-full max-w-2xl"
             >
               <div className="border-b border-white/10 px-5 py-4 sm:px-6">
                 <div className="flex items-start justify-between gap-4">
                   <div>
                     <h3 id="device-settings-modal-title" className="mt-2 font-display text-xl text-sand">
                       {editableDevice?.name ?? "Device Settings"}
                     </h3>
                     <p className="mt-1 text-sm text-sand/60">{editableDevice && deviceTypeLabel(editableDevice)} · {editableDevice && formatDeviceIdLabel(editableDevice)} · {editableDevice?.memory_mb.toLocaleString()} MB</p>
                   </div>
                   <button
                     type="button"
                     onClick={closeDeviceSettingsModal}
                     className="cursor-pointer  border border-white/15 bg-white/10 px-3 text-sand py-1.5 text-sm font-semibold text-sand/70 hover:bg-white/10"
                   >
                     Close
                   </button>
                 </div>
               </div>

               <div className="grid gap-4 px-5 py-5 sm:px-6">
                 <label className="grid gap-1 text-sm text-sand/70">
                   <span>Name</span>
                   <span className="text-xs text-sand/45">Shown throughout the app.</span>
                   <input
                     className=" field px-3 py-2 text-sm"
                     value={deviceModalDraft.name}
                     onChange={(event) => setDeviceModalDraft({ ...deviceModalDraft, name: event.target.value })}
                   />
                 </label>
                 <label className="grid gap-1 text-sm text-sand/70">
                   <span>Priority</span>
                   <span className="text-xs text-sand/45">Higher values are chosen first.</span>
                   <input className=" field px-3 py-2 text-sm" type="number" value={deviceModalDraft.priority} onChange={(event) => setDeviceModalDraft({ ...deviceModalDraft, priority: Number(event.target.value) || 0 })} />
                 </label>
                 <label className="grid gap-1 text-sm text-sand/70">
                   <span>Max Threads</span>
                   <span className="text-xs text-sand/45">Caps worker threads for this device.</span>
                   <input className=" field px-3 py-2 text-sm" type="number" value={deviceModalDraft.max_threads} onChange={(event) => setDeviceModalDraft({ ...deviceModalDraft, max_threads: Number(event.target.value) || 0 })} />
                 </label>
                 <label className="grid gap-1 text-sm text-sand/70">
                   <span>Max Slots</span>
                   <span className="text-xs text-sand/45">Set 0 to allow unlimited jobs.</span>
                   <input className=" field px-3 py-2 text-sm" type="number" min={0} value={deviceModalDraft.max_slots} onChange={(event) => setDeviceModalDraft({ ...deviceModalDraft, max_slots: parseNonNegativeInput(event.target.value) })} />
                 </label>
               </div>

               <div className="flex flex-wrap justify-end gap-2 border-t border-white/10 px-5 py-4 sm:px-6">
                 <button
                   type="button"
                   onClick={closeDeviceSettingsModal}
                   className="cursor-pointer  border border-white/15 bg-white/10 px-3 text-sand py-1.5 text-sm font-semibold text-sand/70 hover:bg-white/10"
                 >
                   Cancel
                 </button>
                 <button
                   type="button"
                   onClick={handleDeviceModalSave}
                   className="cursor-pointer bg-sand px-4 py-1.5 text-sm font-semibold text-canvas hover:bg-sand/80 disabled:cursor-not-allowed disabled:opacity-60"
                 >
                   Save Changes
                 </button>
               </div>
             </Modal>
           ) : null}

          {isLoading && devices.length === 0 ? <p className=" border border-dashed border-white/15 px-4 py-6 text-sm text-sand/60">Loading...</p> : null}
          {devices.map((device) => {
            const owningPool = poolDeviceToPool.get(device.id);
            const inPool = owningPool !== undefined;
            return (
              <article
                key={device.id}
                className={`surface-muted p-4 transition-shadow ${draggedDeviceId === device.id ? "shadow-lg ring-2 ring-amber/60" : ""}`}
                draggable={!isReordering}
                onDragStart={(event) => handleDragStart(event, device.id)}
                onDragOver={handleDragOver}
                onDragEnd={handleDragEnd}
                onDrop={() => handleDeviceDrop(device.id)}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-display text-base">{device.name}</h3>
                    </div>
                    <p className="mt-1 text-sm text-sand/70">{deviceTypeLabel(device)} · {formatDeviceIdLabel(device)} · {device.memory_mb.toLocaleString()} MB</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {inPool ? (
                      <span className="badge-accent px-3 py-1.5 text-xs font-semibold">
                        {owningPool.name}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => updateDeviceDraft(device.id, { enabled: !device.enabled })}
                        className={`cursor-pointer  border px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors ${device.enabled ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25" : "border-white/15 bg-white/10 text-sand/55 hover:bg-white/10"}`}
                      >
                        {device.enabled ? "Enabled" : "Disabled"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => openDeviceSettingsModal(device)}
                      className="cursor-pointer btn-secondary px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors hover:bg-white/10"
                    >
                      Settings
                    </button>
                  </div>
                </div>

                {savingDeviceIds.includes(device.id) || pendingDeviceIds.includes(device.id) ? (
                  <p className="mt-3 text-sm text-sand/55">
                    {savingDeviceIds.includes(device.id) ? "Saving..." : "Saving changes..."}
                  </p>
                ) : null}
              </article>
            );
          })}
          {devices.length === 0 && !isLoading ? <p className=" border border-dashed border-white/15 px-4 py-6 text-sm text-sand/60">No devices detected yet.</p> : null}
        </div>

        {setupMode ? (
          <div className="mt-5 flex items-center justify-between gap-3  border border-white/10 px-4 py-4 text-sm text-sand/70">
            <p>{enabledDevices > 0 ? `${enabledDevices} device${enabledDevices === 1 ? " is" : "s are"} ready.` : "Enable at least one device to continue."}</p>
            <button className=" bg-sand px-4 py-2 font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="button" onClick={onContinue} disabled={enabledDevices === 0 || pendingDeviceIds.length > 0 || savingDeviceIds.length > 0}>
              Continue to Models
            </button>
          </div>
        ) : null}
      </article>
    </section>
  );
}
