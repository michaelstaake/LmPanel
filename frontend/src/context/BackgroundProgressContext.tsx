import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useAuth } from "./AuthContext";
import { apiGet } from "../lib/api";
import { clearModelsCatalogCache } from "../lib/modelsCatalog";
import { useToast } from "./ToastContext";
import { type FetchProgressRecord } from "../lib/records";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatPercent(loaded: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((loaded / total) * 100));
}

function formatEtaFromStart(loaded: number, total: number, startedAt: number | null): number | null {
  if (startedAt == null || loaded <= 0 || total <= 0) return null;
  const percent = (loaded / total) * 100;
  if (percent < 5 || loaded >= total) return null;
  return Math.max(1, Math.ceil((((total - loaded) / loaded) * Math.max(1, Date.now() - startedAt)) / 1000));
}

function formatEta(seconds: number): string {
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  }
  return `${seconds}s`;
}

type UploadProgressState = {
  loaded: number;
  total: number;
};

type BackgroundProgressState = {
  isFetching: boolean;
  fetchJobId: string | null;
  fetchProgress: UploadProgressState;
  fetchFileName: string | null;
  fetchStartedAt: number | null;
  fetchUrl: string;
  isUploading: boolean;
  isProcessingUpload: boolean;
  uploadProgress: UploadProgressState;
  uploadFileName: string | null;
  uploadStartedAt: number | null;
  uploadClock: number;
  isScanning: boolean;
  uploadMode: "model" | "files";
};

const initialState: BackgroundProgressState = {
  isFetching: false,
  fetchJobId: null,
  fetchProgress: { loaded: 0, total: 0 },
  fetchFileName: null,
  fetchStartedAt: null,
  fetchUrl: "",
  isUploading: false,
  isProcessingUpload: false,
  uploadProgress: { loaded: 0, total: 0 },
  uploadFileName: null,
  uploadStartedAt: null,
  uploadClock: Date.now(),
  isScanning: false,
  uploadMode: "model",
};

interface BackgroundProgressContextType extends BackgroundProgressState {
  startFetch: (url: string) => void;
  cancelFetch: () => void;
  startUpload: (mode: "model" | "files", totalBytes: number, fileName?: string | null) => void;
  completeUploadRequest: () => void;
  transitionToProcessing: () => void;
  stopUpload: () => void;
  startScan: () => void;
  stopScan: () => void;
  updateUploadProgress: (progress: UploadProgressState) => void;
  updateUploadClock: (clock: number) => void;
  resetFetch: () => void;
  setFetchJobId: (jobId: string | null) => void;
  setFetchFileName: (fileName: string | null) => void;
  setUploadMode: (mode: "model" | "files") => void;
}

export const BackgroundProgressContext = createContext<BackgroundProgressContextType | null>(null);

export function BackgroundProgressProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const { showError, showSuccess, showInfo, dismissToast } = useToast();
  const [state, setState] = useState<BackgroundProgressState>(initialState);
  const tokenRef = useRef(token);

  tokenRef.current = token;

  const refreshData = useCallback(async (activeToken: string) => {
    try {
      await apiGet<{ models: unknown[]; devices: unknown[]; pools: unknown[] }>(
        "/api/models?_t=" + Date.now(),
        activeToken,
      );
      clearModelsCatalogCache();
      window.location.reload();
    } catch {
      // Silently fail - data will refresh on next page visit
    }
  }, []);

  const startFetch = useCallback((url: string) => {
    showInfo("Fetching model...", {
      id: "models-fetch-info",
      content: (
        <div className="flex flex-col gap-2">
          <p className="font-semibold">Fetching model...</p>
          <div className="h-1.5 w-full overflow-hidden  bg-blue-200/60">
            <div className="h-full  bg-blue-500 transition-[width]" style={{ width: "0%" }} />
          </div>
          <div className="flex items-center justify-between text-xs text-blue-700/70">
            <span>0%</span>
            <span>0 B / 0 B</span>
          </div>
        </div>
      ),
    });
    setState((prev) => ({
      ...prev,
      isFetching: true,
      fetchJobId: null,
      fetchProgress: { loaded: 0, total: 0 },
      fetchFileName: null,
      fetchStartedAt: Date.now(),
      fetchUrl: url,
    }));
  }, [showInfo]);

  const cancelFetch = useCallback(() => {
    setState((prev) => {
      if (prev.fetchJobId) {
        const t = tokenRef.current;
        if (t) {
          apiGet(`/api/models/fetch/${prev.fetchJobId}`, t).catch(() => {});
          fetch(`/api/models/fetch/${prev.fetchJobId}`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${t}` },
          }).catch(() => {});
        }
      }
      dismissToast("models-fetch-info");
      return {
        ...prev,
        isFetching: false,
        fetchJobId: null,
        fetchProgress: { loaded: 0, total: 0 },
        fetchFileName: null,
        fetchStartedAt: null,
        fetchUrl: "",
      };
    });
  }, [dismissToast]);

  const startUpload = useCallback((mode: "model" | "files", totalBytes: number, fileName?: string | null) => {
    const title = mode === "files" ? "Uploading files..." : "Uploading model...";
    showInfo(title, {
      id: "models-upload-info",
      content: (
        <div className="flex flex-col gap-2">
          <p className="font-semibold">{title}</p>
          {fileName ? (
            <p className="truncate text-xs text-blue-700/60" title={fileName}>
              {fileName}
            </p>
          ) : null}
          <div className="h-1.5 w-full overflow-hidden  bg-blue-200/60">
            <div className="h-full  bg-blue-500 transition-[width]" style={{ width: "0%" }} />
          </div>
          <div className="flex items-center justify-between text-xs text-blue-700/70">
            <span>0%</span>
            <span>0 B / {formatBytes(totalBytes)}</span>
          </div>
        </div>
      ),
    });
    setState((prev) => ({
      ...prev,
      isUploading: true,
      isProcessingUpload: false,
      uploadProgress: { loaded: 0, total: totalBytes },
      uploadFileName: fileName ?? null,
      uploadStartedAt: Date.now(),
      uploadClock: Date.now(),
      uploadMode: mode,
    }));
  }, [showInfo]);

  const completeUploadRequest = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isUploading: false,
      uploadProgress: { loaded: prev.uploadProgress.total || prev.uploadProgress.loaded, total: prev.uploadProgress.total || prev.uploadProgress.loaded },
    }));
  }, []);

  const transitionToProcessing = useCallback(() => {
    const title = state.uploadMode === "files" ? "Processing files" : "Finishing upload...";
    const detail = state.uploadMode === "files"
      ? "Saving uploaded files to the server."
      : "Saving the model to the server.";
    showInfo(title, {
      id: "models-upload-info",
      content: (
        <div className="flex flex-col gap-2">
          <p className="font-semibold">{title}</p>
          <p className="text-sm text-blue-700/80">{detail}</p>
          {state.uploadFileName ? (
            <div className="flex items-center gap-2 text-xs text-blue-700/70">
              <svg className="h-3.5 w-3.5 animate-spin text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              <span className="truncate">{state.uploadFileName}</span>
            </div>
          ) : null}
        </div>
      ),
    });
    setState((prev) => ({
      ...prev,
      isUploading: false,
      isProcessingUpload: true,
    }));
  }, [showInfo, state.uploadFileName, state.uploadMode]);

  const stopUpload = useCallback(() => {
    dismissToast("models-upload-info");
    setState((prev) => ({
      ...prev,
      isUploading: false,
      isProcessingUpload: false,
      uploadProgress: { loaded: 0, total: 0 },
      uploadFileName: null,
      uploadStartedAt: null,
      uploadClock: Date.now(),
    }));
  }, [dismissToast]);

  const startScan = useCallback(() => {
    setState((prev) => ({ ...prev, isScanning: true }));
  }, []);

  const stopScan = useCallback(() => {
    setState((prev) => ({ ...prev, isScanning: false }));
  }, []);

  const updateUploadProgress = useCallback((progress: UploadProgressState) => {
    setState((prev) => ({ ...prev, uploadProgress: progress }));
  }, []);

  const updateUploadClock = useCallback((clock: number) => {
    setState((prev) => ({ ...prev, uploadClock: clock }));
  }, []);

  const resetFetch = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isFetching: false,
      fetchJobId: null,
      fetchProgress: { loaded: 0, total: 0 },
      fetchFileName: null,
      fetchStartedAt: null,
      fetchUrl: "",
    }));
  }, []);

  const setFetchJobId = useCallback((jobId: string | null) => {
    setState((prev) => ({ ...prev, fetchJobId: jobId }));
  }, []);

  const setFetchFileName = useCallback((fileName: string | null) => {
    setState((prev) => ({ ...prev, fetchFileName: fileName }));
  }, []);

  const setUploadMode = useCallback((mode: "model" | "files") => {
    setState((prev) => ({ ...prev, uploadMode: mode }));
  }, []);

  // Fetch job progress polling
  useEffect(() => {
    if (!state.isFetching || !state.fetchJobId || !token) {
      return;
    }

    const pollFetch = async () => {
      try {
        const response = await apiGet<FetchProgressRecord>(`/api/models/fetch/${state.fetchJobId}`, token);
        setState((prev) => {
          if (prev.fetchJobId !== state.fetchJobId) return prev;
          const loaded = response.downloaded;
          const total = response.total ?? 0;
          const percent = formatPercent(loaded, total);
          const etaSeconds = formatEtaFromStart(loaded, total, prev.fetchStartedAt);
          const fileName = response.file_name ?? prev.fetchFileName;
          const progressContent = (
            <div className="flex flex-col gap-2">
              <p className="font-semibold">Fetching model...</p>
              {fileName ? (
                <p className="truncate text-xs text-blue-700/60" title={fileName}>
                  {fileName}
                </p>
              ) : null}
              <div className="h-1.5 w-full overflow-hidden  bg-blue-200/60">
                <div className="h-full  bg-blue-500 transition-[width]" style={{ width: `${percent}%` }} />
              </div>
              <div className="flex items-center justify-between text-xs text-blue-700/70">
                <span>{percent}%</span>
                <span>
                  {formatBytes(loaded)} / {formatBytes(total)}
                  {etaSeconds != null ? ` · ${formatEta(etaSeconds)} remaining` : ""}
                </span>
              </div>
            </div>
          );
          showInfo("Fetching model...", { id: "models-fetch-info", content: progressContent });
          return {
            ...prev,
            fetchProgress: { loaded, total },
            fetchFileName: fileName,
          };
        });

        if (response.status === "completed") {
          setState((prev) => {
            if (prev.fetchJobId !== state.fetchJobId) return prev;
            if (response.model) {
              window.location.reload();
            }
            dismissToast("models-fetch-info");
            showSuccess("Model fetched successfully.", { id: "models-fetch-success" });
            return {
              ...prev,
              isFetching: false,
              fetchJobId: null,
              fetchProgress: { loaded: 0, total: 0 },
              fetchFileName: null,
              fetchStartedAt: null,
              fetchUrl: "",
            };
          });
          if (token) {
            setTimeout(() => refreshData(token), 500);
          }
        } else if (response.status === "error") {
          setState((prev) => {
            if (prev.fetchJobId !== state.fetchJobId) return prev;
            dismissToast("models-fetch-info");
            showError(response.error ?? "Fetch failed.", { id: "models-fetch-error" });
            return {
              ...prev,
              isFetching: false,
              fetchJobId: null,
              fetchProgress: { loaded: 0, total: 0 },
              fetchFileName: null,
              fetchStartedAt: null,
              fetchUrl: "",
            };
          });
        }
      } catch {
        setState((prev) => {
          if (prev.fetchJobId !== state.fetchJobId) return prev;
          dismissToast("models-fetch-info");
          showError("Fetch job not found or expired.", { id: "models-fetch-error" });
          return {
            ...prev,
            isFetching: false,
            fetchJobId: null,
            fetchProgress: { loaded: 0, total: 0 },
            fetchFileName: null,
            fetchStartedAt: null,
            fetchUrl: "",
          };
        });
      }
    };

    const intervalId = window.setInterval(pollFetch, 1000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [state.isFetching, state.fetchJobId, token]);

  // Upload clock timer
  useEffect(() => {
    if (!state.isUploading) {
      return;
    }

    const intervalId = window.setInterval(() => {
      updateUploadClock(Date.now());
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [state.isUploading, updateUploadClock]);

  useEffect(() => {
    if (!state.isUploading) {
      return;
    }

    const loaded = state.uploadProgress.loaded;
    const total = state.uploadProgress.total;
    const percent = formatPercent(loaded, total);
    const isUploadBytesComplete = total > 0 && loaded >= total;
    const now = state.uploadClock || Date.now();
    const elapsedSeconds = Math.max(1, Math.floor((now - (state.uploadStartedAt || now)) / 1000));
    const etaSeconds = percent > 0 && percent < 100
      ? Math.round((elapsedSeconds / percent) * (100 - percent))
      : null;
    const title = state.uploadMode === "files" ? "Uploading files" : "Uploading model";
    const processingTitle = state.uploadMode === "files" ? "Processing files" : "Finishing upload...";
    const processingDetail = state.uploadMode === "files"
      ? "Saving uploaded files to the server."
      : "Saving the model to the server.";
    const progressContent = isUploadBytesComplete ? (
      <div className="flex flex-col gap-2">
        <p className="font-semibold">{processingTitle}</p>
        <p className="text-sm text-blue-700/80">{processingDetail}</p>
        {state.uploadFileName ? (
          <div className="flex items-center gap-2 text-xs text-blue-700/70">
            <svg className="h-3.5 w-3.5 animate-spin text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span className="truncate">{state.uploadFileName}</span>
          </div>
        ) : null}
      </div>
    ) : (
      <div className="flex flex-col gap-2">
        <p className="font-semibold">{title}...</p>
        {state.uploadFileName ? (
          <p className="truncate text-xs text-blue-700/60" title={state.uploadFileName}>
            {state.uploadFileName}
          </p>
        ) : null}
        <div className="h-1.5 w-full overflow-hidden  bg-blue-200/60">
          <div className="h-full  bg-blue-500 transition-[width]" style={{ width: `${percent}%` }} />
        </div>
        <div className="flex items-center justify-between text-xs text-blue-700/70">
          <span>{percent}%</span>
          <span>
            {formatBytes(loaded)} / {formatBytes(total)}
            {etaSeconds != null ? ` · ${formatEta(etaSeconds)} remaining` : ""}
          </span>
        </div>
      </div>
    );
    showInfo(title, { id: "models-upload-info", content: progressContent });
  }, [state.isUploading, state.uploadClock, state.uploadFileName, state.uploadProgress, state.uploadStartedAt, state.uploadMode, showInfo]);

  const contextValue: BackgroundProgressContextType = {
    ...state,
    startFetch,
    cancelFetch,
    startUpload,
    completeUploadRequest,
    transitionToProcessing,
    stopUpload,
    startScan,
    stopScan,
    updateUploadProgress,
    updateUploadClock,
    resetFetch,
    setFetchJobId,
    setFetchFileName,
    setUploadMode,
  };

  return (
    <BackgroundProgressContext.Provider value={contextValue}>
      {children}
    </BackgroundProgressContext.Provider>
  );
}

export function useBackgroundProgress(): BackgroundProgressContextType {
  const context = useContext(BackgroundProgressContext);
  if (!context) {
    throw new Error("useBackgroundProgress must be used within BackgroundProgressProvider");
  }
  return context;
}
