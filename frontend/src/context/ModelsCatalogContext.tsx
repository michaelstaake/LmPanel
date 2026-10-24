import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { fetchV1Models } from "../lib/api";
import {
  beginModelsCatalogRefresh,
  buildCatalogFromV1Response,
  clearModelsCatalogCache,
  createInitialCatalogLoadState,
  emptyModelsCatalog,
  invalidateModelsCatalogState,
  readModelsCatalogCache,
  settleModelsCatalogRequest,
  writeModelsCatalogCache,
  type ModelsCatalogData,
  type ModelsCatalogLoadState,
} from "../lib/modelsCatalog";
import { useAuth } from "./AuthContext";
import { useToast } from "./ToastContext";

export type { ModelCardDetails } from "../lib/modelsCatalog";

const MODELS_CATALOG_TIMEOUT_MS = 20_000;

type ModelsCatalogContextValue = ModelsCatalogData & {
  isLoadingModels: boolean;
  isRefreshingModels: boolean;
  refreshModels: () => Promise<void>;
  invalidateModelsCatalog: () => void;
};

const ModelsCatalogContext = createContext<ModelsCatalogContextValue | null>(null);

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
    || (error instanceof Error && error.name === "AbortError");
}

export function ModelsCatalogProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const { showError } = useToast();
  const [loadState, setLoadState] = useState<ModelsCatalogLoadState>(() => createInitialCatalogLoadState(readModelsCatalogCache()));
  const catalogRef = useRef(loadState.catalog);
  const requestIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const refreshModels = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = ++requestIdRef.current;
    const hasCachedModels = catalogRef.current.models.length > 0;
    const timeoutId = window.setTimeout(() => controller.abort(), MODELS_CATALOG_TIMEOUT_MS);

    setLoadState((current) => beginModelsCatalogRefresh(current));

    try {
      const response = await fetchV1Models(token || undefined, controller.signal);
      const catalog = buildCatalogFromV1Response(response);
      if (!mountedRef.current || requestId !== requestIdRef.current) {
        return;
      }
      setLoadState((current) => {
        if (requestId !== requestIdRef.current) {
          return current;
        }
        catalogRef.current = catalog;
        writeModelsCatalogCache(catalog);
        return settleModelsCatalogRequest(current, requestId, requestId, { ok: true, catalog });
      });
    } catch (error) {
      if (!mountedRef.current || requestId !== requestIdRef.current) {
        return;
      }
      if (!hasCachedModels) {
        const message = !isAbortError(error) && error instanceof Error ? error.message : "Failed to load models";
        showError(message);
      }
      setLoadState((current) => {
        if (requestId !== requestIdRef.current) {
          return current;
        }
        return settleModelsCatalogRequest(current, requestId, requestId, { ok: false });
      });
    } finally {
      window.clearTimeout(timeoutId);
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    }
  }, [showError, token]);

  const invalidateModelsCatalog = useCallback(() => {
    clearModelsCatalogCache();
    catalogRef.current = emptyModelsCatalog;
    setLoadState(invalidateModelsCatalogState());
    void refreshModels();
  }, [refreshModels]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const cached = readModelsCatalogCache();
    catalogRef.current = cached ?? emptyModelsCatalog;
    setLoadState(createInitialCatalogLoadState(cached));
    void refreshModels();
  }, [token, refreshModels]);

  const value: ModelsCatalogContextValue = {
    ...loadState.catalog,
    isLoadingModels: loadState.isLoadingModels,
    isRefreshingModels: loadState.isRefreshingModels,
    refreshModels,
    invalidateModelsCatalog,
  };

  return <ModelsCatalogContext.Provider value={value}>{children}</ModelsCatalogContext.Provider>;
}

export function useModelsCatalog(): ModelsCatalogContextValue {
  const context = useContext(ModelsCatalogContext);
  if (!context) {
    throw new Error("useModelsCatalog must be used within ModelsCatalogProvider");
  }
  return context;
}
