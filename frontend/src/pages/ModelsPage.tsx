import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, apiPostFormWithProgress, pollUntilTaskComplete } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { useBackgroundProgress } from "../context/BackgroundProgressContext";
import { formatDeviceIdLabel } from "../lib/deviceIds";
import { formatShardStatus, isProtectedModelFile, validateModelUploadFiles } from "../lib/ggufShards";
import { AssetDeleteResponse, AssetUploadResponse, DeviceRecord, GpuPoolRecord, ModelActivationResponse, ModelRecord, ModelRuntimeState, ModelUpdateResponse, ScanResponse, UploadResponse } from "../lib/records";
import Modal from "../components/ui/Modal";
import ReorderButtons from "../components/ui/ReorderButtons";

const AUTO_SAVE_DELAY_MS = 700;
const REORDER_AUTO_SAVE_DELAY_MS = 1000;
const MODEL_RUNTIME_POLL_INTERVAL_MS = 5000;
const MODEL_ASSET_ACCEPT = ".gguf,.mmproj,.json,.txt,.yaml,.yml,.bin,.safetensors";

function getModelRuntimeState(model: ModelRecord): ModelRuntimeState {
  return model.runtime_state ?? (model.activated ? "recovering" : "disabled");
}

function getActivationButtonPresentation(model: ModelRecord, isActivationLoading: boolean) {
  if (isActivationLoading) {
    return {
      label: "Loading...",
      className: "border-sky-300 bg-sky-100 text-sky-800",
      title: undefined,
    };
  }

  switch (getModelRuntimeState(model)) {
    case "running":
      return {
        label: "Enabled",
        className: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25",
        title: undefined,
      };
    case "recovering":
      return {
        label: "Recovering...",
        className: "border-amber-500/40 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25",
        title: model.runtime_error ?? "Model is restarting in the background.",
      };
    case "error":
      return {
        label: "Error",
        className: "border-rose-500/40 bg-rose-500/15 text-rose-200 hover:bg-rose-500/25",
        title: model.runtime_error ?? "Model is enabled but not running. Click to disable and troubleshoot.",
      };
    default:
      return {
        label: "Disabled",
        className: "border-white/15 bg-white/10 text-sand/55 hover:bg-white/10",
        title: undefined,
      };
  }
}

function stripUrlQueryString(url: string): string {
  const questionIndex = url.indexOf("?");
  return questionIndex === -1 ? url : url.slice(0, questionIndex);
}

const CONTEXT_LENGTH_MODE_OPTIONS = [
  { label: "Auto", value: "auto" },
  { label: "Custom", value: "custom" },
] as const;

type ContextLengthMode = (typeof CONTEXT_LENGTH_MODE_OPTIONS)[number]["value"];

type AssignmentTarget = {
  label: string;
  value: string;
  assignment_mode: "pinned" | "pool";
  id: number;
};

function buildAssignmentTargets(devices: DeviceRecord[], pools: GpuPoolRecord[]): AssignmentTarget[] {
  const pooledDeviceIds = new Set(pools.flatMap((pool) => pool.devices.map((device) => device.id)));

  return [
    ...devices.filter((device) => device.enabled && !pooledDeviceIds.has(device.id)).map((device) => ({
      label: `${device.name} (${device.vendor} device, ${formatDeviceIdLabel(device)})`,
      value: `device:${device.id}`,
      assignment_mode: "pinned" as const,
      id: device.id,
    })),
    ...pools.map((pool) => ({
      label: `${pool.name} (${pool.vendor} pool, ${pool.devices.length} GPU${pool.devices.length === 1 ? "" : "s"})`,
      value: `pool:${pool.id}`,
      assignment_mode: "pool" as const,
      id: pool.id,
    })),
  ];
}

function getAssignmentTargetValue(model: ModelRecord): string {
  if (model.assignment_mode === "pool" && model.pinned_pool_id != null) {
    return `pool:${model.pinned_pool_id}`;
  }

  if (model.assignment_mode === "pinned" && model.pinned_device_id != null) {
    return `device:${model.pinned_device_id}`;
  }

  return "";
}

function buildAssignmentUpdate(targetValue: string): Pick<ModelRecord, "assignment_mode" | "pinned_device_id" | "pinned_pool_id"> {
  if (targetValue.startsWith("pool:")) {
    return {
      assignment_mode: "pool",
      pinned_device_id: null,
      pinned_pool_id: Number(targetValue.slice(5)) || null,
    };
  }

  if (targetValue.startsWith("device:")) {
    return {
      assignment_mode: "pinned",
      pinned_device_id: Number(targetValue.slice(7)) || null,
      pinned_pool_id: null,
    };
  }

  return {
    assignment_mode: "auto",
    pinned_device_id: null,
    pinned_pool_id: null,
  };
}

function getDeviceDropdownValue(model: ModelRecord, assignmentTargets: AssignmentTarget[]): string {
  if (model.assignment_mode === "auto") {
    return "auto";
  }

  const targetValue = getAssignmentTargetValue(model);
  if (!targetValue || !assignmentTargets.some((target) => target.value === targetValue)) {
    return "auto";
  }

  return targetValue;
}

function normalizeAssignmentDraft(model: ModelRecord, assignmentTargets: AssignmentTarget[]): ModelRecord {
  const deviceValue = getDeviceDropdownValue(model, assignmentTargets);
  if (deviceValue === "auto") {
    return {
      ...model,
      assignment_mode: "auto",
      pinned_device_id: null,
      pinned_pool_id: null,
    };
  }

  return { ...model, ...buildAssignmentUpdate(deviceValue) };
}

type ModelsPageProps = {
  setupMode?: boolean;
  onComplete?: () => void;
};

type UploadModalMode = "model" | "files";

function buildModelPayload(model: ModelRecord) {
  return {
    alias: model.alias,
    description: model.description,
    system_prompt: model.system_prompt,
    chat_template: model.chat_template,
    context_length: model.context_length,
    gpu_layers: 99,
    threads: model.threads,
    temperature: model.temperature,
    top_p: model.top_p,
    min_p: model.min_p,
    top_k: model.top_k,
    presence_penalty: model.presence_penalty,
    repetition_penalty: model.repetition_penalty,
    tool_calling_enabled: model.tool_calling_enabled,
    discourage_thinking: model.discourage_thinking,
    default_thinking_enabled: model.default_thinking_enabled,
    thinking_capability: model.thinking_capability,
    vision_enabled: model.vision_enabled,
    web_search_enabled: model.web_search_enabled,
    rag_enabled: model.rag_enabled,
    flash_attention_enabled: model.flash_attention_enabled,
    memory_mapping_enabled: model.memory_mapping_enabled,
    assignment_mode: model.assignment_mode,
    pinned_device_id: model.assignment_mode === "pinned" ? model.pinned_device_id : null,
    pinned_pool_id: model.assignment_mode === "pool" ? model.pinned_pool_id : null,
  };
}

function serializeModelConfig(model: ModelRecord) {
  return JSON.stringify(buildModelPayload(model));
}

function mergeSavedModel(current: ModelRecord, sent: ModelRecord, saved: ModelRecord): ModelRecord {
  const merged: ModelRecord = { ...saved };

  function assignField<K extends keyof ModelRecord>(key: K, value: ModelRecord[K]) {
    merged[key] = value;
  }

  for (const key of Object.keys(current) as Array<keyof ModelRecord>) {
    if (current[key] !== sent[key]) {
      assignField(key, current[key]);
    }
  }
  return merged;
}

function sortModels(models: ModelRecord[]) {
  return [...models].sort((left, right) => left.priority - right.priority || left.id - right.id);
}

function moveModel(models: ModelRecord[], fromIndex: number, toIndex: number) {
  const nextModels = [...models];
  const [movedModel] = nextModels.splice(fromIndex, 1);
  nextModels.splice(toIndex, 0, movedModel);
  return nextModels.map((model, index) => ({ ...model, priority: index }));
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}


function formatModelActivationSuccessMessage(modelAlias: string, elapsedSeconds?: number): string {
  if (typeof elapsedSeconds !== "number" || Number.isNaN(elapsedSeconds)) {
    return `${modelAlias} enabled.`;
  }

  return `${modelAlias} enabled. Loaded in ${elapsedSeconds.toFixed(2)} seconds.`;
}

export default function ModelsPage({ setupMode = false, onComplete }: ModelsPageProps) {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [hasLoadedModels, setHasLoadedModels] = useState(false);
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [pools, setPools] = useState<GpuPoolRecord[]>([]);
  const [settingsModelId, setSettingsModelId] = useState<number | null>(null);
  const [modalDraft, setModalDraft] = useState<ModelRecord | null>(null);
  const [modalContextLengthMode, setModalContextLengthMode] = useState<ContextLengthMode>("custom");
  const [modalNumericDrafts, setModalNumericDraftsState] = useState<Record<string, string>>({});
  const [isSavingModal, setIsSavingModal] = useState(false);
  const [isDeletingModal, setIsDeletingModal] = useState(false);
  const [deletingFileName, setDeletingFileName] = useState<string | null>(null);
  const modelReorderSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadTargetModelId, setUploadTargetModelId] = useState<number | null>(null);
  const [selectedUploadFiles, setSelectedUploadFiles] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [fetchUrlInput, setFetchUrlInput] = useState("");
  const [isFetchModalOpen, setIsFetchModalOpen] = useState(false);
  const {
    isFetching,
    isUploading,
    uploadMode,
    isScanning: contextIsScanning,
    startFetch,
    cancelFetch,
    startUpload,
    completeUploadRequest,
    transitionToProcessing,
    stopUpload,
    startScan,
    stopScan,
    updateUploadProgress,
    resetFetch,
    setFetchJobId: contextSetFetchJobId,
    setUploadMode: contextSetUploadMode,
  } = useBackgroundProgress();
  const [isReordering, setIsReordering] = useState(false);
  const [savingModelIds, setSavingModelIds] = useState<number[]>([]);
  const [pendingModelIds, setPendingModelIds] = useState<number[]>([]);
  const [loadingActivationIds, setLoadingActivationIds] = useState<number[]>([]);
  const latestModelsRef = useRef<ModelRecord[]>([]);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const savedConfigRef = useRef<Record<number, string>>({});
  const savedActivationRef = useRef<Record<number, boolean>>({});
  const saveTimeoutsRef = useRef<Record<number, number>>({});
  const savingIdsRef = useRef<Set<number>>(new Set());
  const resaveRequestedRef = useRef<Set<number>>(new Set());
  const loadingActivationIdsRef = useRef<number[]>([]);

  useEffect(() => {
    loadingActivationIdsRef.current = loadingActivationIds;
  }, [loadingActivationIds]);

  useEffect(() => {
    latestModelsRef.current = models;
  }, [models]);

  useEffect(() => {
    if (!token) {
      setHasLoadedModels(false);
      return;
    }
    void refreshData(token);
  }, [token]);

  useEffect(() => {
    if (!token) {
      return;
    }

    const pollRuntimeStatus = async () => {
      try {
        const modelsResponse = await apiGet<ModelRecord[]>("/api/models", token);
        const polledById = new Map(modelsResponse.map((model) => [model.id, model]));
        setModels((current) =>
          current.map((item) => {
            const polled = polledById.get(item.id);
            if (!polled) {
              return item;
            }

            const isActivationLoading = loadingActivationIdsRef.current.includes(item.id);
            return {
              ...item,
              activated: isActivationLoading ? item.activated : polled.activated,
              runtime_state: polled.runtime_state,
              runtime_error: polled.runtime_error,
            };
          })
        );
      } catch {
        // Ignore transient poll failures; the next tick will retry.
      }
    };

    const intervalId = window.setInterval(() => {
      void pollRuntimeStatus();
    }, MODEL_RUNTIME_POLL_INTERVAL_MS);

    return () => window.clearInterval(intervalId);
  }, [token]);

  async function refreshData(activeToken: string) {
    setIsLoading(true);
    try {
      const [modelsResponse, devicesResponse, poolResponse] = await Promise.all([
        apiGet<ModelRecord[]>("/api/models", activeToken),
        apiGet<DeviceRecord[]>("/api/devices", activeToken),
        apiGet<GpuPoolRecord[]>("/api/devices/pools", activeToken),
      ]);
      const orderedModels = sortModels(modelsResponse);
      savedConfigRef.current = Object.fromEntries(orderedModels.map((model) => [model.id, serializeModelConfig(model)]));
      savedActivationRef.current = Object.fromEntries(orderedModels.map((model) => [model.id, model.activated]));
      setModels(orderedModels);
      setDevices(devicesResponse);
      setPools(poolResponse);
      setPendingModelIds([]);
      setLoadingActivationIds([]);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load model data", { id: "models-error" });
    } finally {
      setHasLoadedModels(true);
      setIsLoading(false);
    }
  }

  useEffect(() => () => {
    Object.values(saveTimeoutsRef.current).forEach((timeoutId) => window.clearTimeout(timeoutId));
    if (modelReorderSaveTimerRef.current) clearTimeout(modelReorderSaveTimerRef.current);
  }, []);

  useEffect(() => {
    setModalDraft((current) => {
      if (!current || current.assignment_mode === "auto") {
        return current;
      }
      const targets = buildAssignmentTargets(devices, pools);
      if (getDeviceDropdownValue(current, targets) !== "auto") {
        return current;
      }
      return normalizeAssignmentDraft(current, targets);
    });
  }, [devices, pools]);

  useEffect(() => {
    if (settingsModelId == null) {
      return;
    }
    const currentModel = models.find((model) => model.id === settingsModelId);
    if (!currentModel) {
      return;
    }
    setModalDraft((draft) => {
      if (!draft || draft.id !== settingsModelId) {
        return draft;
      }
      return {
        ...draft,
        directory_files: currentModel.directory_files,
        directory_size: currentModel.directory_size,
        mmproj_file_name: currentModel.mmproj_file_name,
        shard_count: currentModel.shard_count,
        shards_complete: currentModel.shards_complete,
        missing_shards: currentModel.missing_shards,
      };
    });
  }, [models, settingsModelId]);

  function scheduleModelSave(modelId: number) {
    const existingTimeout = saveTimeoutsRef.current[modelId];
    if (existingTimeout) {
      window.clearTimeout(existingTimeout);
    }

    setPendingModelIds((current) => (current.includes(modelId) ? current : [...current, modelId]));

    saveTimeoutsRef.current[modelId] = window.setTimeout(() => {
      delete saveTimeoutsRef.current[modelId];
      void persistModel(modelId);
    }, AUTO_SAVE_DELAY_MS);
  }

  function updateModelDraft(modelId: number, updates: Partial<ModelRecord>) {
    setModels((current) => current.map((model) => (model.id === modelId ? { ...model, ...updates } : model)));
    scheduleModelSave(modelId);
  }

  function resetUploadSelection() {
    setSelectedUploadFiles([]);
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  }

  function openModelUploadModal() {
    contextSetUploadMode("model");
    setUploadTargetModelId(null);
    resetUploadSelection();
    setIsUploadModalOpen(true);
  }

  function openAssetUploadModal(modelId: number) {
    contextSetUploadMode("files");
    setUploadTargetModelId(modelId);
    resetUploadSelection();
    setIsUploadModalOpen(true);
  }

  function applyUploadedModel(model: ModelRecord) {
    savedConfigRef.current[model.id] = serializeModelConfig(model);
    savedActivationRef.current[model.id] = model.activated;
    setModels((current) => sortModels([...current.filter((item) => item.id !== model.id), model]));
    setModalDraft((current) => {
      if (!current || current.id !== model.id) {
        return current;
      }
      return {
        ...current,
        model_dir_name: model.model_dir_name,
        mmproj_file_name: model.mmproj_file_name,
        directory_files: model.directory_files,
        directory_size: model.directory_size,
        shard_count: model.shard_count,
        shards_complete: model.shards_complete,
        missing_shards: model.missing_shards,
      };
    });
  }

  function handleUploadSelection(fileList: FileList | null) {
    setSelectedUploadFiles(Array.from(fileList ?? []));
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    if (uploadMode === "model" && selectedUploadFiles.length === 0) {
      showError("Choose a .gguf file to upload.", { id: "models-error" });
      return;
    }

    if (uploadMode === "files" && (selectedUploadFiles.length === 0 || uploadTargetModelId == null)) {
      showError("Choose one or more files to upload.", { id: "models-error" });
      return;
    }

    const filesToUpload = selectedUploadFiles;
    if (uploadMode === "model") {
      const validationError = validateModelUploadFiles(filesToUpload.map((file) => file.name));
      if (validationError) {
        showError(validationError, { id: "models-error" });
        return;
      }
    }

    const formData = new FormData();
    if (uploadMode === "model") {
      if (filesToUpload.length === 1) {
        formData.append("file", filesToUpload[0]);
      } else {
        filesToUpload.forEach((file) => formData.append("files", file));
      }
    } else {
      filesToUpload.forEach((file) => formData.append("files", file));
    }
    const totalBytes = filesToUpload.reduce((total, file) => total + file.size, 0);
    const uploadLabel = uploadMode === "model"
      ? filesToUpload[0]?.name ?? null
      : filesToUpload.length === 1
        ? filesToUpload[0]?.name ?? null
        : `${filesToUpload[0]?.name ?? "Files"} + ${filesToUpload.length - 1} more`;

    startUpload(uploadMode, totalBytes, uploadLabel);
    setIsUploadModalOpen(false);

    try {
      if (uploadMode === "model") {
        const response = await apiPostFormWithProgress<UploadResponse>(
          "/api/models/upload",
          formData,
          token,
          (progress) => {
            const total = progress.total || totalBytes;
            updateUploadProgress({ loaded: progress.loaded, total });
          },
          () => {
            completeUploadRequest();
            transitionToProcessing();
          },
        );
        try {
          const taskResult = await pollUntilTaskComplete(response.task_id, token);
          stopUpload();
          resetUploadSelection();
          if (taskResult.status === "error") {
            showError(taskResult.error ?? "Upload processing failed", { id: "models-error" });
          } else {
            showSuccess(
              filesToUpload.length === 1
                ? `Uploaded ${filesToUpload[0]?.name}.`
                : `Uploaded ${filesToUpload.length} shard files for ${filesToUpload[0]?.name}.`,
              { id: "models-success" },
            );
            await refreshData(token);
          }
        } catch (pollError) {
          stopUpload();
          resetUploadSelection();
          try {
            await refreshData(token);
          } catch {
            showError(pollError instanceof Error ? pollError.message : "Upload processing failed", { id: "models-error" });
          }
        }
      } else {
        const response = await apiPostFormWithProgress<AssetUploadResponse>(
          `/api/models/${uploadTargetModelId}/files`,
          formData,
          token,
          (progress) => {
            const total = progress.total || totalBytes;
            updateUploadProgress({ loaded: progress.loaded, total });
          },
          () => {
            completeUploadRequest();
            transitionToProcessing();
          },
        );
        applyUploadedModel(response.model);
        stopUpload();
        resetUploadSelection();
        showSuccess(`Uploaded ${response.uploaded.length} file${response.uploaded.length === 1 ? "" : "s"} to ${response.model.alias}.`, { id: "models-success" });
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : uploadMode === "model" ? "Upload failed" : "File upload failed", { id: "models-error" });
      stopUpload();
    }
  }

  async function handleScan() {
    if (!token) {
      return;
    }

    startScan();

    try {
      const response = await apiPost<Record<string, never>, ScanResponse>("/api/models/scan", {}, token);
      await refreshData(token);
      showSuccess(`Scan finished. Found ${response.discovered} files and added ${response.added} new models.`, { id: "models-success" });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Scan failed", { id: "models-error" });
    } finally {
      stopScan();
    }
  }

  function openFetchModal() {
    resetFetch();
    setIsFetchModalOpen(true);
  }

  async function handleFetch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !fetchUrlInput.trim()) {
      return;
    }

    const url = stripUrlQueryString(fetchUrlInput.trim());
    if (!url.endsWith(".gguf")) {
      showError("URL must point to a .gguf file.", { id: "models-fetch-error" });
      return;
    }

    startFetch(url);
    setIsFetchModalOpen(false);

    try {
      const response = await apiPost<{ url: string }, { status: string; job_id: string }>("/api/models/fetch", { url }, token);
      contextSetFetchJobId(response.job_id);
    } catch (error) {
      resetFetch();
      setFetchUrlInput("");
      showError(error instanceof Error ? error.message : "Failed to start fetch.", { id: "models-fetch-error" });
    }
  }

  async function persistModel(modelId: number) {
    if (!token) {
      return;
    }

    if (savingIdsRef.current.has(modelId)) {
      resaveRequestedRef.current.add(modelId);
      return;
    }

    const model = latestModelsRef.current.find((item) => item.id === modelId);
    if (!model) {
      return;
    }

    const configChanged = savedConfigRef.current[modelId] !== serializeModelConfig(model);
    const activationChanged = savedActivationRef.current[modelId] !== model.activated;

    if (!configChanged && !activationChanged) {
      setPendingModelIds((current) => current.filter((id) => id !== modelId));
      return;
    }

    savingIdsRef.current.add(modelId);
    setSavingModelIds((current) => (current.includes(modelId) ? current : [...current, modelId]));
    setPendingModelIds((current) => current.filter((id) => id !== modelId));

    let savedSuccessfully = false;

    try {
      if (configChanged) {
        const response = await apiPatch<Record<string, string | number | boolean | null>, ModelUpdateResponse>(`/api/models/${model.id}`, buildModelPayload(model), token);
        savedConfigRef.current[model.id] = serializeModelConfig(response.model);
        if (!activationChanged) {
          savedActivationRef.current[model.id] = response.model.activated;
        }
        setModels((current) =>
          current.map((item) => {
            if (item.id !== model.id) {
              return item;
            }
            const merged = mergeSavedModel(item, model, response.model);
            return {
              ...merged,
              activated: activationChanged ? item.activated : merged.activated,
            };
          })
        );
      }

      if (activationChanged) {
        await apiPost<Record<string, never>, { status: string }>(`/api/models/${model.id}/${model.activated ? "activate" : "deactivate"}`, {}, token);
        savedActivationRef.current[model.id] = model.activated;
        setModels((current) => current.map((item) => (item.id === model.id ? { ...item, activated: model.activated } : item)));
      }

      showSuccess(`Saved settings for ${model.alias}.`, { id: "models-success" });
      savedSuccessfully = true;
    } catch (error) {
      if (activationChanged) {
        const previousActivation = savedActivationRef.current[model.id];
        setModels((current) => current.map((item) => (item.id === model.id ? { ...item, activated: previousActivation } : item)));
      }
      showError(error instanceof Error ? error.message : "Model update failed", { id: "models-error" });
    } finally {
      savingIdsRef.current.delete(modelId);
      setSavingModelIds((current) => current.filter((id) => id !== modelId));

      const latestModel = latestModelsRef.current.find((item) => item.id === modelId);
      const configStillDirty = latestModel ? savedConfigRef.current[modelId] !== serializeModelConfig(latestModel) : false;
      const activationStillDirty = latestModel ? savedActivationRef.current[modelId] !== latestModel.activated : false;
      const shouldResave = savedSuccessfully && (resaveRequestedRef.current.has(modelId) || configStillDirty || activationStillDirty);
      resaveRequestedRef.current.delete(modelId);

      if (shouldResave) {
        scheduleModelSave(modelId);
      }
    }
  }

  async function persistModelOrder(nextModels: ModelRecord[], previousModels: ModelRecord[]) {
    if (!token) {
      return;
    }

    setIsReordering(true);

    try {
      await apiPost<{ models: { id: number; priority: number }[] }, { status: string }>(
        "/api/models/reorder",
        {
          models: nextModels.map((model, index) => ({ id: model.id, priority: index })),
        },
        token,
      );
      showSuccess("Saved model order.", { id: "models-success" });
      scheduleModelReorderSave();
    } catch (error) {
      setModels(previousModels);
      showError(error instanceof Error ? error.message : "Failed to save model order", { id: "models-error" });
    } finally {
      setIsReordering(false);
    }
  }

  async function toggleModelActivation(model: ModelRecord) {
    if (!token) {
      return;
    }
    const runtimeState = getModelRuntimeState(model);
    const nextActivated = runtimeState === "disabled";
    setLoadingActivationIds((current) => (current.includes(model.id) ? current : [...current, model.id]));
    try {
      const response = await apiPost<Record<string, never>, ModelActivationResponse | { status: string }>(`/api/models/${model.id}/${nextActivated ? "activate" : "deactivate"}`, {}, token);
      const nextRuntimeState: ModelRuntimeState = nextActivated ? "running" : "disabled";
      setModels((current) =>
        current.map((item) =>
          item.id === model.id
            ? {
                ...item,
                activated: nextActivated,
                runtime_state: nextRuntimeState,
                runtime_error: null,
              }
            : item
        )
      );
      savedActivationRef.current[model.id] = nextActivated;
      showSuccess(
        nextActivated
          ? formatModelActivationSuccessMessage(model.alias, "elapsed_seconds" in response ? response.elapsed_seconds : undefined)
          : runtimeState === "error"
            ? `${model.alias} disabled. You can re-enable it after troubleshooting.`
            : `${model.alias} disabled.`,
        { id: "models-success" }
      );
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to update model activation", { id: "models-error" });
    } finally {
      setLoadingActivationIds((current) => current.filter((itemId) => itemId !== model.id));
    }
  }

  function openSettingsModal(model: ModelRecord) {
    const targets = buildAssignmentTargets(devices, pools);
    setSettingsModelId(model.id);
    setModalDraft(normalizeAssignmentDraft({ ...model }, targets));
    setModalContextLengthMode(model.max_context_length != null && model.context_length === model.max_context_length ? "auto" : "custom");
    setModalNumericDraftsState({});
  }

  function closeSettingsModal() {
    setSettingsModelId(null);
    setModalDraft(null);
    setModalContextLengthMode("custom");
    setModalNumericDraftsState({});
  }

  function updateModalDraft(updates: Partial<ModelRecord>) {
    setModalDraft((current) => (current ? { ...current, ...updates } : null));
  }

  function setModalNumericDraft(field: string, value: string) {
    setModalNumericDraftsState((current) => ({ ...current, [field]: value }));
  }

  function commitModalNumericDraft(field: keyof ModelRecord, value: string, clamp: (n: number) => number) {
    setModalNumericDraftsState((current) => {
      const next = { ...current };
      delete next[field as string];
      return next;
    });
    const parsed = parseFloat(value);
    if (!isNaN(parsed) && value.trim() !== "") {
      updateModalDraft({ [field]: clamp(parsed) } as Partial<ModelRecord>);
    }
  }

  function updateModalContextLengthMode(mode: ContextLengthMode) {
    setModalContextLengthMode(mode);
    setModalNumericDraftsState((current) => {
      if (!("context_length" in current)) {
        return current;
      }
      const next = { ...current };
      delete next.context_length;
      return next;
    });

    if (mode === "auto" && modalDraft?.max_context_length != null) {
      updateModalDraft({ context_length: modalDraft.max_context_length });
    }
  }

  async function saveModalDraft() {
    if (!token || !modalDraft) {
      return;
    }
    setIsSavingModal(true);
    try {
      const normalizedDraft = normalizeAssignmentDraft(modalDraft, assignmentTargets);
      const response = await apiPatch<Record<string, string | number | boolean | null>, ModelUpdateResponse>(`/api/models/${modalDraft.id}`, buildModelPayload(normalizedDraft), token);
      savedConfigRef.current[modalDraft.id] = serializeModelConfig(response.model);
      setModels((current) =>
        current.map((item) => {
          if (item.id !== modalDraft.id) {
            return item;
          }
          return { ...response.model, activated: item.activated };
        })
      );
      showSuccess(`Saved settings for ${response.model.alias}.`, { id: "models-success" });
      closeSettingsModal();
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save model settings", { id: "models-error" });
    } finally {
      setIsSavingModal(false);
    }
  }

  async function deleteModelFile(fileName: string) {
    if (!token || !modalDraft) {
      return;
    }

    if (modalDraft.activated) {
      showError("Disable this model before deleting files from it.", { id: "models-error" });
      return;
    }

    if (isProtectedModelFile(modalDraft, fileName)) {
      return;
    }

    const confirmed = window.confirm(`Delete ${fileName} from ${modalDraft.alias}?`);
    if (!confirmed) {
      return;
    }

    setDeletingFileName(fileName);

    try {
      const response = await apiDelete<AssetDeleteResponse>(
        `/api/models/${modalDraft.id}/files/${encodeURIComponent(fileName)}`,
        token,
      );
      applyUploadedModel(response.model);
      showSuccess(`Deleted ${fileName}.`, { id: "models-success" });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to delete file", { id: "models-error" });
    } finally {
      setDeletingFileName(null);
    }
  }

  async function deleteModalModel() {
    if (!token || !modalDraft) {
      return;
    }

    if (modalDraft.activated) {
      showError("Disable this model before deleting it.", { id: "models-error" });
      return;
    }

    const confirmed = window.confirm(`Delete ${modalDraft.alias}? This removes the registered model and its GGUF file.`);
    if (!confirmed) {
      return;
    }

    setIsDeletingModal(true);

    try {
      await apiDelete<{ status: string }>(`/api/models/${modalDraft.id}`, token);
      setModels((current) => current.filter((item) => item.id !== modalDraft.id));
      delete savedConfigRef.current[modalDraft.id];
      delete savedActivationRef.current[modalDraft.id];
      const existingTimeout = saveTimeoutsRef.current[modalDraft.id];
      if (existingTimeout) {
        window.clearTimeout(existingTimeout);
        delete saveTimeoutsRef.current[modalDraft.id];
      }
      savingIdsRef.current.delete(modalDraft.id);
      resaveRequestedRef.current.delete(modalDraft.id);
      setPendingModelIds((current) => current.filter((id) => id !== modalDraft.id));
      setSavingModelIds((current) => current.filter((id) => id !== modalDraft.id));
      setLoadingActivationIds((current) => current.filter((id) => id !== modalDraft.id));
      showSuccess(`Deleted ${modalDraft.alias}.`, { id: "models-success" });
      closeSettingsModal();
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to delete model", { id: "models-error" });
    } finally {
      setIsDeletingModal(false);
    }
  }

  async function handleMoveModel(modelId: number, direction: "up" | "down") {
    if (isReordering) {
      return;
    }

    const sorted = sortModels(models);
    const fromIndex = sorted.findIndex((model) => model.id === modelId);
    if (fromIndex === -1) {
      return;
    }

    const toIndex = direction === "up" ? fromIndex - 1 : fromIndex + 1;
    if (toIndex < 0 || toIndex >= sorted.length) {
      return;
    }

    const previousModels = models;
    const nextModels = moveModel(sorted, fromIndex, toIndex);
    setModels(nextModels);
    void persistModelOrder(nextModels, previousModels);
  }

  function scheduleModelReorderSave() {
    if (modelReorderSaveTimerRef.current) {
      clearTimeout(modelReorderSaveTimerRef.current);
    }
    modelReorderSaveTimerRef.current = setTimeout(() => {
      modelReorderSaveTimerRef.current = null;
      const latestModels = latestModelsRef.current;
      for (const model of latestModels) {
        scheduleModelSave(model.id);
      }
    }, REORDER_AUTO_SAVE_DELAY_MS);
  }

  const activeModels = models.filter((model) => getModelRuntimeState(model) === "running").length;
  const assignmentTargets = buildAssignmentTargets(devices, pools);
  const uploadContextModel = uploadTargetModelId != null ? models.find((model) => model.id === uploadTargetModelId) ?? null : null;
  const showModelReorder = models.length > 1;

  function closeUploadModal() {
    if (isUploading) {
      return;
    }

    setIsUploadModalOpen(false);
    if (uploadMode === "files") {
      setUploadTargetModelId(null);
    }
    contextSetUploadMode("model");
    resetUploadSelection();
  }

  return (
    <section className="grid gap-4">
      <article className="surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="mt-2 font-display text-xl">{setupMode ? "Step 3: Models" : "Models"}</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              onClick={openModelUploadModal}
              disabled={isUploading || isFetching}
            >
              {isUploading ? "Uploading..." : "Upload Model File"}
            </button>
            <button
              className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              onClick={openFetchModal}
              disabled={isUploading || isFetching}
            >
              {isFetching ? "Fetching..." : "Fetch Model File"}
            </button>
            <button
              className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              onClick={handleScan}
              disabled={contextIsScanning || isUploading || isFetching}
            >
              {contextIsScanning ? "Scanning..." : "Scan Models Folder"}
            </button>
          </div>
        </div>

        {setupMode ? <p className="mt-2 max-w-3xl text-sm text-sand/70">Register and activate at least one model to complete setup.</p> : null}

        <div className="mt-5 space-y-4">
          {models.map((model, index) => {
            const isActivationLoading = loadingActivationIds.includes(model.id);
            const activationButton = getActivationButtonPresentation(model, isActivationLoading);

            return (
              <article
                key={model.id}
                className="surface-muted p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    {showModelReorder ? (
                      <ReorderButtons
                        onMoveUp={() => void handleMoveModel(model.id, "up")}
                        onMoveDown={() => void handleMoveModel(model.id, "down")}
                        canMoveUp={index > 0}
                        canMoveDown={index < models.length - 1}
                        disabled={isReordering}
                      />
                    ) : null}
                    <div className="min-w-0 flex-1">
                    <h3 className="font-display text-base">{model.alias}</h3>
                    <p className="mt-0.5 text-sm text-sand/55">
                      {model.file_name}
                      {model.directory_size > 0 ? <span className="ml-2 text-xs text-sand/35">({formatFileSize(model.directory_size)} on disk{model.directory_files && model.directory_files.length > 1 ? ` · ${model.directory_files.length} files` : ""})</span> : null}
                    </p>
                    {model.description ? <p className="mt-1 text-sm text-sand/70">{model.description}</p> : null}
                  </div>
                </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {savingModelIds.includes(model.id) || pendingModelIds.includes(model.id) ? (
                      <span className="text-xs text-sand/45">{savingModelIds.includes(model.id) ? "Saving..." : "Pending..."}</span>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void toggleModelActivation(model)}
                      className={`cursor-pointer  border px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors disabled:cursor-not-allowed ${activationButton.className}`}
                      disabled={isActivationLoading}
                      title={activationButton.title}
                    >
                      {activationButton.label}
                    </button>
                    <button
                      className="cursor-pointer  btn-secondary px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors hover:bg-white/10"
                      type="button"
                      onClick={() => openSettingsModal(model)}
                    >
                      Settings
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
          {!hasLoadedModels ? <p className=" border border-dashed border-white/15 px-4 py-6 text-sm text-sand/60">Loading...</p> : null}
          {hasLoadedModels && models.length === 0 ? <p className=" border border-dashed border-white/15 px-4 py-6 text-sm text-sand/60">No models registered yet.</p> : null}
        </div>

        {setupMode ? (
          <div className="mt-5 flex items-center justify-between gap-3  border border-white/10 px-4 py-4 text-sm text-sand/70">
            <p>{activeModels > 0 ? `${activeModels} model${activeModels === 1 ? " is" : "s are"} active.` : "Activate at least one model to finish setup."}</p>
            <button className=" bg-sand px-4 py-2 font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="button" onClick={onComplete} disabled={activeModels === 0 || pendingModelIds.length > 0 || savingModelIds.length > 0}>
              Finish Setup
            </button>
          </div>
        ) : null}
      </article>

      {modalDraft ? (
        <Modal
          open={settingsModelId !== null && !isUploadModalOpen}
          onClose={closeSettingsModal}
          labelledBy="model-settings-modal-title"
          panelClassName="w-full max-w-2xl"
        >
          <div className="p-6">
            <h2 id="model-settings-modal-title" className="font-display text-xl">Model Settings</h2>

            <div className="mt-5 grid gap-5">
              <section>
                {formatShardStatus(modalDraft.shard_count, modalDraft.shards_complete, modalDraft.missing_shards) ? (
                  <div
                    className={`mb-3 border px-3 py-2 text-sm ${
                      modalDraft.shards_complete
                        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                        : "border-amber-200 bg-amber-50 text-amber-900"
                    }`}
                  >
                    {formatShardStatus(modalDraft.shard_count, modalDraft.shards_complete, modalDraft.missing_shards)}
                  </div>
                ) : null}
                <div className="overflow-hidden  border border-white/10">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-white/10 text-left text-xs font-semibold text-sand/60">
                        <th className="px-4 py-2.5">{modalDraft.model_dir_name}</th>
                        <th className="px-4 py-2.5 text-right">{formatFileSize(modalDraft.directory_size ?? 0)}</th>
                        <th className="w-20 px-4 py-2.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/5">
                      {(modalDraft.directory_files ?? []).map((file) => (
                        <tr key={file.name} className="text-sand/70">
                          <td className="px-4 py-2.5 font-mono text-xs">
                            {file.name}
                            {modalDraft.mmproj_file_name === file.name ? (
                              <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide text-sand/40">mmproj</span>
                            ) : null}
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs text-sand/55">{formatFileSize(file.size)}</td>
                          <td className="px-4 py-2.5 text-right">
                            {!isProtectedModelFile(modalDraft, file.name) ? (
                              <button
                                type="button"
                                className="text-xs font-semibold text-red-400 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-60"
                                onClick={() => void deleteModelFile(file.name)}
                                disabled={
                                  isSavingModal
                                  || isDeletingModal
                                  || isUploading
                                  || deletingFileName !== null
                                  || modalDraft.activated
                                }
                                title={
                                  modalDraft.activated
                                    ? "Disable this model before deleting files."
                                    : `Delete ${file.name}`
                                }
                              >
                                {deletingFileName === file.name ? "Deleting..." : "Delete"}
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                      <tr>
                        <td className="px-4 py-3" colSpan={3}>
                          <button
                            type="button"
                            className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
                            onClick={() => openAssetUploadModal(modalDraft.id)}
                            disabled={isSavingModal || isDeletingModal || isUploading || deletingFileName !== null}
                          >
                            Add Files
                          </button>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>

              <section>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sand/45">General</p>
                <div className="grid gap-3">
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Name</span>
                    <span className="text-xs text-sand/45">Used in API requests and displayed on the front end.</span>
                    <input className=" field px-3 py-2 text-sm" value={modalDraft.alias} onChange={(event) => updateModalDraft({ alias: event.target.value })} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Description</span>
                    <span className="text-xs text-sand/45">Optional, displayed on the front end.</span>
                    <input className=" field px-3 py-2 text-sm" value={modalDraft.description} onChange={(event) => updateModalDraft({ description: event.target.value })} />
                  </label>
                </div>
              </section>

              <section>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sand/45">Devices</p>
                <div className="grid gap-3">
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Device</span>
                    <span className="text-xs text-sand/45">Auto lets LmPanel choose the most sensible device.</span>
                    <select
                      className=" field px-3 py-2 text-sm"
                      value={getDeviceDropdownValue(modalDraft, assignmentTargets)}
                      onChange={(event) => {
                        const value = event.target.value;
                        if (value === "auto") {
                          updateModalDraft({
                            assignment_mode: "auto",
                            pinned_device_id: null,
                            pinned_pool_id: null,
                          });
                          return;
                        }
                        updateModalDraft(buildAssignmentUpdate(value));
                      }}
                    >
                      <option value="auto">Auto</option>
                      {assignmentTargets.map((target) => (
                        <option key={target.value} value={target.value}>{target.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>CPU threads</span>
                    <span className="text-xs text-sand/45">CPU worker threads for this model.</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={1} value={modalNumericDrafts.threads ?? String(modalDraft.threads)} onChange={(event) => setModalNumericDraft("threads", event.target.value)} onBlur={(event) => commitModalNumericDraft("threads", event.target.value, (n) => Math.max(1, Math.round(n)))} />
                  </label>
                </div>
              </section>

              <section>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sand/45">Context Length</p>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Mode</span>
                    <span className="text-xs text-sand/45">Auto uses the model default limit.</span>
                    <select
                      className=" field px-3 py-2 text-sm"
                      value={modalContextLengthMode}
                      onChange={(event) => updateModalContextLengthMode(event.target.value as ContextLengthMode)}
                    >
                      {CONTEXT_LENGTH_MODE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value} disabled={option.value === "auto" && modalDraft.max_context_length == null}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Context Length</span>
                    <span className="text-xs text-sand/45">Larger context lengths may increase memory usage.</span>
                    <input
                      className=" field px-3 py-2 text-sm disabled:bg-white/10 disabled:text-sand/45"
                      type="number"
                      min={256}
                      value={modalNumericDrafts.context_length ?? String(modalDraft.context_length)}
                      onChange={(event) => setModalNumericDraft("context_length", event.target.value)}
                      onBlur={(event) => commitModalNumericDraft("context_length", event.target.value, (n) => Math.max(256, Math.round(n)))}
                      disabled={modalContextLengthMode === "auto"}
                    />
                  </label>
                </div>
              </section>

              <section>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sand/45">Features</p>
                <div className="grid gap-3">
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Thinking capability</span>
                    <span className="text-xs text-sand/45">Auto detects hybrid models (Qwen, Gemma). Override if detection is wrong.</span>
                    <select
                      className=" field px-3 py-2 text-sm"
                      value={modalDraft.thinking_capability}
                      onChange={(event) => updateModalDraft({ thinking_capability: event.target.value })}
                    >
                      <option value="auto">Auto</option>
                      <option value="hybrid">Hybrid (toggle in chat)</option>
                      <option value="always">Always thinks</option>
                      <option value="none">No thinking support</option>
                    </select>
                  </label>
                  {!modalDraft.discourage_thinking && (modalDraft.thinking_capability === "auto" || modalDraft.thinking_capability === "hybrid") ? (
                    <label className="flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70">
                      <input
                        className="mt-1"
                        type="checkbox"
                        checked={modalDraft.default_thinking_enabled}
                        onChange={(event) => updateModalDraft({ default_thinking_enabled: event.target.checked })}
                      />
                      <span className="grid gap-0.5">
                        <span className="text-sm text-sand/70">Default thinking on</span>
                        <span className="text-xs text-sand/45">Initial state of the chat Thinking toggle for this model.</span>
                      </span>
                    </label>
                  ) : null}
                  <label className="flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70">
                    <input className="mt-1" type="checkbox" checked={modalDraft.discourage_thinking} onChange={(event) => updateModalDraft({ discourage_thinking: event.target.checked })} />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Always disable thinking</span>
                      <span className="text-xs text-sand/45">Locks thinking off for this model and hides the chat toggle.</span>
                    </span>
                  </label>
                  <label className="flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70">
                    <input className="mt-1" type="checkbox" checked={modalDraft.tool_calling_enabled} onChange={(event) => updateModalDraft({ tool_calling_enabled: event.target.checked })} />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Tool calling</span>
                      <span className="text-xs text-sand/45">If enabled, lets this model call tools.</span>
                    </span>
                  </label>
                  <label className={`flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70 ${!modalDraft.tool_calling_enabled ? "opacity-50" : ""}`}>
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={modalDraft.web_search_enabled}
                      disabled={!modalDraft.tool_calling_enabled}
                      onChange={(event) => updateModalDraft({ web_search_enabled: event.target.checked })}
                    />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Web search</span>
                      <span className="text-xs text-sand/45">
                        {modalDraft.tool_calling_enabled
                          ? "Allows the model to search the web for current information via the active provider."
                          : "Requires tool calling to be enabled first."}
                      </span>
                    </span>
                  </label>
                  <label className={`flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70 ${!modalDraft.tool_calling_enabled ? "opacity-50" : ""}`}>
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={modalDraft.rag_enabled}
                      disabled={!modalDraft.tool_calling_enabled}
                      onChange={(event) => updateModalDraft({ rag_enabled: event.target.checked })}
                    />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Knowledge Base</span>
                      <span className="text-xs text-sand/45">
                        {modalDraft.tool_calling_enabled
                          ? "Enables Retrieval-Augmented Generation (RAG) features powered by Knowledge Base content"
                          : "Requires tool calling to be enabled first."}
                      </span>
                    </span>
                  </label>
                  <label className="flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70">
                    <input className="mt-1" type="checkbox" checked={modalDraft.vision_enabled} onChange={(event) => updateModalDraft({ vision_enabled: event.target.checked })} />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Vision capable</span>
                      <span className="text-xs text-sand/45">Requires an mmproj file in this model folder to handle images.</span>
                    </span>
                  </label>
                </div>
              </section>

              <section>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sand/45">Behavior</p>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Temperature</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={0} max={2} step={0.05} value={modalNumericDrafts.temperature ?? String(modalDraft.temperature)} onChange={(event) => setModalNumericDraft("temperature", event.target.value)} onBlur={(event) => commitModalNumericDraft("temperature", event.target.value, (n) => Math.min(2, Math.max(0, n)))} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Top P</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={0} max={1} step={0.05} value={modalNumericDrafts.top_p ?? String(modalDraft.top_p)} onChange={(event) => setModalNumericDraft("top_p", event.target.value)} onBlur={(event) => commitModalNumericDraft("top_p", event.target.value, (n) => Math.min(1, Math.max(0, n)))} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Min P</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={0} max={1} step={0.05} value={modalNumericDrafts.min_p ?? String(modalDraft.min_p)} onChange={(event) => setModalNumericDraft("min_p", event.target.value)} onBlur={(event) => commitModalNumericDraft("min_p", event.target.value, (n) => Math.min(1, Math.max(0, n)))} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Top K</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={0} step={1} value={modalNumericDrafts.top_k ?? String(modalDraft.top_k)} onChange={(event) => setModalNumericDraft("top_k", event.target.value)} onBlur={(event) => commitModalNumericDraft("top_k", event.target.value, (n) => Math.max(0, Math.round(n)))} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Presence Penalty</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={-2} max={2} step={0.05} value={modalNumericDrafts.presence_penalty ?? String(modalDraft.presence_penalty)} onChange={(event) => setModalNumericDraft("presence_penalty", event.target.value)} onBlur={(event) => commitModalNumericDraft("presence_penalty", event.target.value, (n) => Math.min(2, Math.max(-2, n)))} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70 md:col-span-2">
                    <span>Repetition Penalty</span>
                    <input className=" field px-3 py-2 text-sm" type="number" min={0} step={0.05} value={modalNumericDrafts.repetition_penalty ?? String(modalDraft.repetition_penalty)} onChange={(event) => setModalNumericDraft("repetition_penalty", event.target.value)} onBlur={(event) => commitModalNumericDraft("repetition_penalty", event.target.value, (n) => Math.max(0, n))} />
                  </label>
                </div>
              </section>

              <section>
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sand/45">Advanced</p>
                <div className="grid gap-3">
                  <label className="flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70">
                    <input className="mt-1" type="checkbox" checked={modalDraft.flash_attention_enabled} onChange={(event) => updateModalDraft({ flash_attention_enabled: event.target.checked })} />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Flash Attention</span>
                      <span className="text-xs text-sand/45">Use flash attention to speed up inference.</span>
                    </span>
                  </label>
                  <label className="flex gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70">
                    <input className="mt-1" type="checkbox" checked={modalDraft.memory_mapping_enabled} onChange={(event) => updateModalDraft({ memory_mapping_enabled: event.target.checked })} />
                    <span className="grid gap-0.5">
                      <span className="text-sm text-sand/70">Memory Mapping</span>
                      <span className="text-xs text-sand/45">Map model weights from disk into memory. Disable if loading fails on your system.</span>
                    </span>
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>System Prompt</span>
                    <span className="text-xs text-sand/45">Default instructions sent with each chat.</span>
                    <textarea className="min-h-24  field px-3 py-2 text-sm" value={modalDraft.system_prompt} onChange={(event) => updateModalDraft({ system_prompt: event.target.value })} />
                  </label>
                  <label className="grid gap-1 text-sm text-sand/70">
                    <span>Chat Template</span>
                    <span className="text-xs text-sand/45">Formats messages for this model.</span>
                    <textarea className="min-h-24  field px-3 py-2 text-sm" value={modalDraft.chat_template} onChange={(event) => updateModalDraft({ chat_template: event.target.value })} />
                  </label>
                </div>
              </section>
            </div>

            <div className="mt-6 flex items-center justify-between gap-3 border-t border-white/10 pt-4">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className=" btn-danger px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => void deleteModalModel()}
                  disabled={isSavingModal || isDeletingModal || modalDraft.activated}
                  title={modalDraft.activated ? "Disable this model before deleting it." : undefined}
                >
                  {isDeletingModal ? "Deleting..." : "Delete Model"}
                </button>
              </div>
              <div className="flex items-center gap-3">
              <button
                type="button"
                className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
                onClick={closeSettingsModal}
                disabled={isSavingModal || isDeletingModal}
              >
                Cancel
              </button>
              <button
                type="button"
                className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => void saveModalDraft()}
                disabled={isSavingModal || isDeletingModal}
              >
                {isSavingModal ? "Saving..." : modalDraft.activated ? "Save and Reload" : "Save"}
              </button>
              </div>
            </div>
          </div>
        </Modal>
      ) : null}

      <Modal
        open={isUploadModalOpen}
        onClose={closeUploadModal}
        labelledBy="model-upload-modal-title"
        panelClassName="w-full max-w-xl"
      >
        <form className="p-6" onSubmit={handleUpload}>
          <h2 id="model-upload-modal-title" className="font-display text-xl">{uploadMode === "files" ? "Add Files" : "Upload Model File"}</h2>
          <p className="mt-1 text-sm text-sand/55">
            {uploadMode === "files"
              ? `Select additional files to store in ${uploadContextModel?.model_dir_name ?? "this model folder"}.`
              : "Select one `.gguf` file, or all shards of a split model (`*-00001-of-00002.gguf`, etc.)."}
          </p>

          <div className="mt-5 grid gap-3">
            <input
              ref={uploadInputRef}
              id="model-upload-input"
              className="block w-full  field px-3 py-2 text-sm file:mr-3 file: file:border-0 file:bg-amber file:px-3 file:py-2 file:font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              type="file"
              accept={uploadMode === "files" ? MODEL_ASSET_ACCEPT : ".gguf"}
              multiple
              onChange={(event) => handleUploadSelection(event.target.files)}
              disabled={isUploading}
            />
            {selectedUploadFiles.length > 0 ? (
              <div className=" border border-white/10 px-3 py-3 text-sm text-sand/65">
                <p className="font-semibold text-sand/75">Selected</p>
                <div className="mt-2 grid gap-1">
                  {selectedUploadFiles.map((file) => (
                    <p key={`${file.name}-${file.size}`}>{file.name}</p>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="mt-6 flex items-center justify-end gap-3 border-t border-white/10 pt-4">
            <button
              type="button"
              className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={closeUploadModal}
              disabled={isUploading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className=" bg-amber px-4 py-2 text-sm font-semibold text-sand disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isUploading || selectedUploadFiles.length === 0}
            >
              {isUploading ? "Uploading..." : uploadMode === "files" ? "Add Files" : "Upload Model File"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
          open={isFetchModalOpen}
        onClose={() => {
          if (!isFetching) {
            setFetchUrlInput("");
          }
          setIsFetchModalOpen(false);
        }}
        labelledBy="model-fetch-modal-title"
        panelClassName="w-full max-w-xl"
      >
        <form className="p-6" onSubmit={handleFetch}>
          <h2 id="model-fetch-modal-title" className="font-display text-xl">Fetch Model File</h2>
          <p className="mt-1 text-sm text-sand/55">
            Enter a URL to download a `.gguf` model file directly to the server. Adding models to your LmPanel server this way only works with single GGUF file models - to add a sharded GGUF file use the file upload feature.
          </p>

          <div className="mt-5 grid gap-3">
            <label className="grid gap-1 text-sm text-sand/70">
              <input
                className=" field px-3 py-2 text-sm"
                type="url"
                placeholder="https://example.com/model.gguf"
                value={fetchUrlInput}
                onChange={(event) => setFetchUrlInput(stripUrlQueryString(event.target.value))}
                disabled={isFetching}
                required
              />
            </label>
          </div>

          <div className="mt-6 flex items-center justify-between gap-3 border-t border-white/10 pt-4">
            <button
              type="button"
              className=" border border-white/15 px-4 py-2 text-sm font-semibold text-sand hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => {
                setFetchUrlInput("");
                setIsFetchModalOpen(false);
              }}
              disabled={isFetching}
            >
              {isFetching ? "In Progress..." : "Cancel"}
            </button>
            <button
              type="submit"
              className=" bg-amber px-4 py-2 text-sm font-semibold text-sand disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isFetching || !fetchUrlInput.trim()}
            >
              {isFetching ? "Fetching..." : "Fetch Model File"}
            </button>
          </div>
        </form>
      </Modal>
    </section>
  );
}
