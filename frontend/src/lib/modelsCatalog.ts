import { type V1ModelEntry, type V1ModelsResponse } from "./api";

export type ModelCardDetails = {
  description: string;
  contextLength: number | null;
  toolCallingEnabled: boolean;
  webSearchEnabled: boolean;
  visionEnabled: boolean;
  ragEnabled: boolean;
};

export type ModelsCatalogData = {
  models: string[];
  modelCardDetails: Record<string, ModelCardDetails>;
  modelVisionDefaults: Record<string, boolean>;
  modelSearchAvailability: Record<string, boolean>;
  modelThinkingDisabledDefaults: Record<string, boolean>;
  modelThinkingDefaults: Record<string, boolean>;
  modelThinkingControllable: Record<string, boolean>;
  modelThinkingCapabilities: Record<string, string>;
  modelThinkingLevels: Record<string, boolean>;
  modelThinkingCanDisable: Record<string, boolean>;
  modelThinkingLevelDefaults: Record<string, string>;
};

const CACHE_KEY_PREFIX = "lmpanel.v1models.";

function cacheStorageKey(): string {
  if (typeof window === "undefined") {
    return `${CACHE_KEY_PREFIX}default`;
  }
  return `${CACHE_KEY_PREFIX}${window.location.origin}`;
}

export function buildCatalogFromV1Response(response: V1ModelsResponse): ModelsCatalogData {
  const models: string[] = [];
  const modelCardDetails: Record<string, ModelCardDetails> = {};
  const modelVisionDefaults: Record<string, boolean> = {};
  const modelSearchAvailability: Record<string, boolean> = {};
  const modelThinkingDisabledDefaults: Record<string, boolean> = {};
  const modelThinkingDefaults: Record<string, boolean> = {};
  const modelThinkingControllable: Record<string, boolean> = {};
  const modelThinkingCapabilities: Record<string, string> = {};
  const modelThinkingLevels: Record<string, boolean> = {};
  const modelThinkingCanDisable: Record<string, boolean> = {};
  const modelThinkingLevelDefaults: Record<string, string> = {};

  for (const entry of response.data) {
    models.push(entry.id);
    modelCardDetails[entry.id] = {
      description: entry.description?.trim() ?? "",
      contextLength: entry.context_length ?? null,
      toolCallingEnabled: entry.tool_calling_enabled ?? false,
      webSearchEnabled: entry.web_search_enabled ?? false,
      visionEnabled: entry.vision_enabled ?? false,
      ragEnabled: entry.rag_enabled ?? false,
    };
    modelVisionDefaults[entry.id] = entry.vision_enabled ?? false;
    modelSearchAvailability[entry.id] = entry.web_search_available ?? false;
    modelThinkingDisabledDefaults[entry.id] = entry.discourage_thinking ?? false;
    modelThinkingDefaults[entry.id] = entry.default_thinking_enabled ?? true;
    modelThinkingControllable[entry.id] = entry.thinking_controllable ?? false;
    modelThinkingCapabilities[entry.id] = entry.thinking_capability ?? "none";
    modelThinkingLevels[entry.id] =
      entry.thinking_levels ?? (entry.thinking_capability === "levels" || entry.thinking_capability === "hybrid_levels");
    modelThinkingCanDisable[entry.id] =
      entry.thinking_can_disable ?? (entry.thinking_capability === "hybrid" || entry.thinking_capability === "hybrid_levels");
    modelThinkingLevelDefaults[entry.id] = entry.default_thinking_level ?? "medium";
  }

  return {
    models,
    modelCardDetails,
    modelVisionDefaults,
    modelSearchAvailability,
    modelThinkingDisabledDefaults,
    modelThinkingDefaults,
    modelThinkingControllable,
    modelThinkingCapabilities,
    modelThinkingLevels,
    modelThinkingCanDisable,
    modelThinkingLevelDefaults,
  };
}

export function readModelsCatalogCache(): ModelsCatalogData | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = sessionStorage.getItem(cacheStorageKey());
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<ModelsCatalogData>;
    if (!Array.isArray(parsed.models)) {
      return null;
    }
    return {
      models: parsed.models,
      modelCardDetails: parsed.modelCardDetails ?? {},
      modelVisionDefaults: parsed.modelVisionDefaults ?? {},
      modelSearchAvailability: parsed.modelSearchAvailability ?? {},
      modelThinkingDisabledDefaults: parsed.modelThinkingDisabledDefaults ?? {},
      modelThinkingDefaults: parsed.modelThinkingDefaults ?? {},
      modelThinkingControllable: parsed.modelThinkingControllable ?? {},
      modelThinkingCapabilities: parsed.modelThinkingCapabilities ?? {},
      modelThinkingLevels: parsed.modelThinkingLevels ?? {},
      modelThinkingCanDisable: parsed.modelThinkingCanDisable ?? {},
      modelThinkingLevelDefaults: parsed.modelThinkingLevelDefaults ?? {},
    };
  } catch {
    return null;
  }
}

export function writeModelsCatalogCache(data: ModelsCatalogData): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    sessionStorage.setItem(cacheStorageKey(), JSON.stringify(data));
  } catch {
    // Ignore quota or private-mode errors.
  }
}

export function clearModelsCatalogCache(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    sessionStorage.removeItem(cacheStorageKey());
  } catch {
    // Ignore.
  }
}

export type { V1ModelEntry };
