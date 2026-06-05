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
  buildCatalogFromV1Response,
  clearModelsCatalogCache,
  readModelsCatalogCache,
  writeModelsCatalogCache,
  type ModelsCatalogData,
} from "../lib/modelsCatalog";
import { useAuth } from "./AuthContext";
import { useToast } from "./ToastContext";

export type { ModelCardDetails } from "../lib/modelsCatalog";

const emptyCatalog: ModelsCatalogData = {
  models: [],
  modelCardDetails: {},
  modelVisionDefaults: {},
  modelSearchAvailability: {},
  modelThinkingDisabledDefaults: {},
  modelThinkingDefaults: {},
  modelThinkingControllable: {},
  modelThinkingCapabilities: {},
};

type ModelsCatalogContextValue = ModelsCatalogData & {
  isLoadingModels: boolean;
  isRefreshingModels: boolean;
  refreshModels: () => Promise<void>;
  invalidateModelsCatalog: () => void;
};

const ModelsCatalogContext = createContext<ModelsCatalogContextValue | null>(null);

export function ModelsCatalogProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const { showError } = useToast();
  const [catalog, setCatalog] = useState<ModelsCatalogData>(() => readModelsCatalogCache() ?? emptyCatalog);
  const [isLoadingModels, setIsLoadingModels] = useState(() => readModelsCatalogCache() === null);
  const [isRefreshingModels, setIsRefreshingModels] = useState(false);
  const catalogRef = useRef(catalog);
  catalogRef.current = catalog;

  const applyCatalog = useCallback((data: ModelsCatalogData) => {
    setCatalog(data);
    writeModelsCatalogCache(data);
  }, []);

  const refreshModels = useCallback(async () => {
    const hasCachedModels = catalogRef.current.models.length > 0;
    if (!hasCachedModels) {
      setIsLoadingModels(true);
    } else {
      setIsRefreshingModels(true);
    }

    try {
      const response = await fetchV1Models(token || undefined);
      applyCatalog(buildCatalogFromV1Response(response));
    } catch (error) {
      if (!hasCachedModels) {
        showError(error instanceof Error ? error.message : "Failed to load models");
      }
    } finally {
      setIsLoadingModels(false);
      setIsRefreshingModels(false);
    }
  }, [applyCatalog, showError, token]);

  const invalidateModelsCatalog = useCallback(() => {
    clearModelsCatalogCache();
    setCatalog(emptyCatalog);
    setIsLoadingModels(true);
  }, []);

  useEffect(() => {
    const cached = readModelsCatalogCache();
    if (cached) {
      setCatalog(cached);
      setIsLoadingModels(false);
    } else {
      setIsLoadingModels(true);
    }
    void refreshModels();
  }, [token, refreshModels]);

  const value: ModelsCatalogContextValue = {
    ...catalog,
    isLoadingModels,
    isRefreshingModels,
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
