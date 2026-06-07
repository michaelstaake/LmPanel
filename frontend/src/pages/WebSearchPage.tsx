import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  fetchActiveWebSearchProvider,
  fetchWebSearchProviders,
  setActiveWebSearchProvider,
  updateWebSearchProvider,
} from "../lib/api";
import type { ActiveProviderRecord, WebSearchProviderRecord } from "../lib/records";
import SettingsLayout from "./SettingsLayout";

type ProviderDraft = {
  enabled: boolean;
  api_key: string;
  result_count: number;
  result_count_input: string;
};

function buildDraft(provider: WebSearchProviderRecord): ProviderDraft {
  return {
    enabled: provider.enabled,
    api_key: "",
    result_count: provider.result_count,
    result_count_input: String(provider.result_count),
  };
}

export default function WebSearchPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [providers, setProviders] = useState<WebSearchProviderRecord[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ProviderDraft>>({});
  const [activeProviderType, setActiveProviderType] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [savingType, setSavingType] = useState<string | null>(null);
  const [settingActive, setSettingActive] = useState(false);
  const hasLoaded = useRef(false);

  useEffect(() => {
    if (!token || hasLoaded.current) return;
    hasLoaded.current = true;
    void load(token);
  }, [token]);

  async function load(activeToken: string) {
    setIsLoading(true);
    try {
      const [providerList, activeRecord] = await Promise.all([
        fetchWebSearchProviders<WebSearchProviderRecord[]>(activeToken),
        fetchActiveWebSearchProvider<ActiveProviderRecord>(activeToken),
      ]);
      setProviders(providerList);
      setDrafts(Object.fromEntries(providerList.map((p) => [p.provider_type, buildDraft(p)])));
      setActiveProviderType(activeRecord.provider_type);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load web search settings");
    } finally {
      setIsLoading(false);
    }
  }

  function updateDraft(providerType: string, updates: Partial<ProviderDraft>) {
    setDrafts((current) => ({
      ...current,
      [providerType]: { ...current[providerType], ...updates },
    }));
  }

  async function saveProvider(providerType: string) {
    if (!token) return;
    const draft = drafts[providerType];
    if (!draft) return;

    const resultCountParsed = parseInt(draft.result_count_input, 10);
    const finalResultCount = !isNaN(resultCountParsed) ? Math.max(1, Math.min(20, resultCountParsed)) : draft.result_count;

    setSavingType(providerType);

    try {
      const updated = await updateWebSearchProvider<
        { enabled: boolean; api_key?: string; result_count: number },
        WebSearchProviderRecord
      >(
        providerType,
        {
          enabled: draft.enabled,
          ...(draft.api_key !== "" ? { api_key: draft.api_key } : {}),
          result_count: finalResultCount,
        },
        token,
      );

      setProviders((current) => current.map((p) => (p.provider_type === providerType ? updated : p)));
      setDrafts((current) => ({
        ...current,
        [providerType]: { ...buildDraft(updated), api_key: "" },
      }));

      // If this provider is now disabled and was the active provider, clear active
      if (!updated.enabled && activeProviderType === providerType) {
        setActiveProviderType(null);
      }

      showSuccess(`Saved ${updated.display_name} settings.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save provider settings");
    } finally {
      setSavingType(null);
    }
  }

  async function handleSetActive(providerType: string | null) {
    if (!token || settingActive) return;
    setSettingActive(true);
    try {
      await setActiveWebSearchProvider(providerType, token);
      setActiveProviderType(providerType);
      if (providerType) {
        const provider = providers.find((p) => p.provider_type === providerType);
        showSuccess(`${provider?.display_name ?? providerType} set as the active provider.`);
      } else {
        showSuccess("Active provider cleared.");
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to set active provider");
    } finally {
      setSettingActive(false);
    }
  }

  const availableProviders = providers.filter((p) => p.enabled && p.api_key_set);
  const activeProvider = providers.find((p) => p.provider_type === activeProviderType) ?? null;

  // If the current active provider is no longer available, show it grayed out in dropdown
  const dropdownProviders = availableProviders;
  const activeIsUnavailable =
    activeProviderType !== null && !availableProviders.some((p) => p.provider_type === activeProviderType);

  return (
    <SettingsLayout title="Web Search">
      <div className="grid gap-4">
      <article>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="mt-2 font-display text-xl">Web Search</h2>
            <p className="mt-1 max-w-2xl text-sm text-black/60">
              Web search can be used by capable models to research topics, access current events, or read online documentation. Ensure tool calling and web search is enabled in the settings for the model you want to use search capability.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-sm font-semibold text-black/70">Active provider</label>
            <select
              className={`rounded-xl border border-black/15 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60 ${dropdownProviders.length === 0 && !activeIsUnavailable ? "text-black/40" : ""}`}
              value={activeProviderType ?? ""}
              disabled={settingActive || (dropdownProviders.length === 0 && !activeIsUnavailable)}
              onChange={(event) => void handleSetActive(event.target.value === "" ? null : event.target.value)}
            >
              {dropdownProviders.length === 0 && !activeIsUnavailable ? (
                <option value="">No available providers</option>
              ) : (
                <>
                  <option value="">None</option>
                  {dropdownProviders.map((p) => (
                    <option key={p.provider_type} value={p.provider_type}>
                      {p.display_name}
                    </option>
                  ))}
                  {activeIsUnavailable && activeProvider && (
                    <option value={activeProvider.provider_type} disabled>
                      {activeProvider.display_name} (unavailable)
                    </option>
                  )}
                </>
              )}
            </select>
          </div>
        </div>

        {isLoading ? (
          <p className="mt-6 text-sm text-black/50">Loading...</p>
        ) : (
          <div className="mt-6 grid gap-4">
            {providers.map((provider) => {
              const draft = drafts[provider.provider_type];
              if (!draft) return null;
              const isSaving = savingType === provider.provider_type;

              return (
                <article
                  key={provider.provider_type}
                  className="rounded-2xl border border-black/10 bg-[#fffdf7] p-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="font-display text-base">{provider.display_name}</h3>
                      <p className="mt-0.5 text-sm text-black/55">{provider.description}</p>
                    </div>
                    {provider.api_key_set && provider.enabled && (
                      <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                        Configured
                      </span>
                    )}
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <label className="flex items-center gap-3 rounded-xl border border-black/10 bg-white px-3 py-2 text-sm text-black/70 md:col-span-2">
                      <input
                        type="checkbox"
                        checked={draft.enabled}
                        onChange={(event) => updateDraft(provider.provider_type, { enabled: event.target.checked })}
                      />
                      <span className="grid gap-0.5">
                        <span className="text-sm text-black/70">Enabled</span>
                        <span className="text-xs text-black/45">
                          Must be enabled and have an API key set to be selectable as the active provider.
                        </span>
                      </span>
                    </label>

                    <label className="grid gap-1 text-sm text-black/70 md:col-span-2">
                      <span>API Key</span>
                      <span className="text-xs text-black/45">
                        {provider.api_key_set
                          ? "A key is already set. Enter a new value to replace it, or leave blank to keep the existing key."
                          : "Enter your API key."}
                      </span>
                      <input
                        className="rounded-xl border border-black/15 bg-white px-3 py-2 text-sm"
                        type="password"
                        autoComplete="new-password"
                        placeholder={provider.api_key_set ? "••••••••  (key already set)" : "Enter API key"}
                        value={draft.api_key}
                        onChange={(event) => updateDraft(provider.provider_type, { api_key: event.target.value })}
                      />
                    </label>

                    <label className="grid gap-1 text-sm text-black/70">
                      <span>Number of Results</span>
                      <span className="text-xs text-black/45">Results returned per search query (1–20).</span>
                      <input
                        className="rounded-xl border border-black/15 bg-white px-3 py-2 text-sm"
                        type="number"
                        min={1}
                        max={20}
                        value={draft.result_count_input}
                        onChange={(event) =>
                          updateDraft(provider.provider_type, { result_count_input: event.target.value })
                        }
                        onBlur={(event) => {
                          const parsed = parseInt(event.target.value, 10);
                          const clamped = !isNaN(parsed) ? Math.max(1, Math.min(20, parsed)) : draft.result_count;
                          updateDraft(provider.provider_type, {
                            result_count: clamped,
                            result_count_input: String(clamped),
                          });
                        }}
                      />
                    </label>
                  </div>

                  <div className="mt-4 flex justify-end">
                    <button
                      type="button"
                      className="rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={isSaving}
                      onClick={() => void saveProvider(provider.provider_type)}
                    >
                      {isSaving ? "Saving..." : "Save"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </article>
      </div>
    </SettingsLayout>
  );
}
