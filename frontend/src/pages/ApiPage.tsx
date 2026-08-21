import { FormEvent, useEffect, useState } from "react";
import Modal from "../components/ui/Modal";
import { apiDelete, apiGet, apiPost, fetchV1Models, type V1ModelEntry } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { ApiKeyCreateResponse, ApiKeyRecord } from "../lib/records";

const MINUTE_IN_MS = 60 * 1000;
const HOUR_IN_MS = 60 * MINUTE_IN_MS;
const DAY_IN_MS = 24 * HOUR_IN_MS;

type ApiUrlInfoId = "usage" | "models";

function formatLastUsed(value: string | null): string {
  if (!value) {
    return "Never used";
  }

  const elapsedMs = Date.now() - new Date(value).getTime();

  if (elapsedMs < MINUTE_IN_MS) {
    return "Last used less than 1 minute ago";
  }

  if (elapsedMs < HOUR_IN_MS) {
    return "Last used less than 1 hour ago";
  }

  if (elapsedMs < DAY_IN_MS) {
    return "Last used less than 24 hours ago";
  }

  return "Last used more than 24 hours ago";
}

function buildModelsExampleResponse(models: V1ModelEntry[]) {
  return {
    object: "list",
    data: models.map((model) => ({
      id: model.id,
      object: "model",
      created: model.created,
      owned_by: model.owned_by,
      ...(model.description ? { description: model.description } : {}),
    })),
  };
}

function ApiUrlInfoButton({
  label,
  open,
  onToggle,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={`inline-flex h-7 w-7 items-center justify-center text-sand/45 transition hover:text-sand ${open ? "text-sand" : ""}`}
      aria-label={label}
      aria-expanded={open}
      onClick={onToggle}
    >
      <i className="bi bi-info-circle text-[16px] leading-none" aria-hidden="true" />
    </button>
  );
}

export default function ApiPage() {
  const { token, user, setupStatus } = useAuth();
  const { showError, showSuccess } = useToast();
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [latestApiKey, setLatestApiKey] = useState("");
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isApiInfoModalOpen, setIsApiInfoModalOpen] = useState(false);
  const [isLoadingKeys, setIsLoadingKeys] = useState(false);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [revokingKeyId, setRevokingKeyId] = useState<number | null>(null);
  const [v1Models, setV1Models] = useState<V1ModelEntry[]>([]);
  const [isLoadingV1Models, setIsLoadingV1Models] = useState(false);
  const [openInfoId, setOpenInfoId] = useState<ApiUrlInfoId | null>(null);

  useEffect(() => {
    if (!token || !user) {
      setApiKeys([]);
      setV1Models([]);
      return;
    }
    void refreshApiKeys(token);
    void refreshV1Models(token);
  }, [token, user]);

  async function refreshApiKeys(activeToken: string) {
    setIsLoadingKeys(true);
    try {
      const response = await apiGet<ApiKeyRecord[]>("/api/auth/api-keys", activeToken);
      setApiKeys(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load API keys");
    } finally {
      setIsLoadingKeys(false);
    }
  }

  const DEFAULT_API_BASE_URL = "https://localhost:8444";

  const BASE_URL = setupStatus?.api_base_url || import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;
  const API_V1_BASE_URL = `${BASE_URL.replace(/\/$/, "")}/v1`;

  async function refreshV1Models(activeToken: string) {
    setIsLoadingV1Models(true);
    try {
      const response = await fetchV1Models(activeToken);
      setV1Models(response.data);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load v1 models");
    } finally {
      setIsLoadingV1Models(false);
    }
  }

  function toggleInfo(id: ApiUrlInfoId) {
    setOpenInfoId((current) => (current === id ? null : id));
  }

  function closeApiInfoModal() {
    setIsApiInfoModalOpen(false);
    setOpenInfoId(null);
  }

  async function handleCreateApiKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    setIsCreatingKey(true);

    try {
      const response = await apiPost<{ name: string }, ApiKeyCreateResponse>("/api/auth/api-keys", { name: newKeyName }, token);
      setApiKeys((current) => [response.api_key, ...current]);
      setLatestApiKey(response.plain_text_key);
      setNewKeyName("");
      setIsCreateModalOpen(true);
      showSuccess(`Created API key ${response.api_key.name}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "API key creation failed");
    } finally {
      setIsCreatingKey(false);
    }
  }

  async function handleRevokeApiKey(keyId: number) {
    if (!token) {
      return;
    }

    setRevokingKeyId(keyId);

    try {
      await apiDelete<{ status: string }>(`/api/auth/api-keys/${keyId}`, token);
      setApiKeys((current) => current.filter((key) => key.id !== keyId));
      showSuccess("API key revoked.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "API key revoke failed");
    } finally {
      setRevokingKeyId(null);
    }
  }

  async function handleCopyLatestApiKey() {
    if (!latestApiKey) {
      return;
    }

    try {
      await navigator.clipboard.writeText(latestApiKey);
      showSuccess("Copied API key to clipboard.");
    } catch {
      // Fallback for non-secure (HTTP) contexts
      const textarea = document.createElement("textarea");
      textarea.value = latestApiKey;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      try {
        document.execCommand("copy");
        showSuccess("Copied API key to clipboard.");
      } catch {
        showError("Copy failed. Select and copy the key manually.");
      } finally {
        document.body.removeChild(textarea);
      }
    }
  }

  function closeCreateModal() {
    setIsCreateModalOpen(false);
    setLatestApiKey("");
  }

  return (
    <section className="grid gap-4">
      <article className="surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <h2 className="font-display text-2xl">API Keys</h2>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-secondary px-4 py-3 text-sm font-semibold" type="button" onClick={() => setIsApiInfoModalOpen(true)}>
              API info
            </button>
            <button className="btn-secondary px-4 py-3 text-sm font-semibold" type="button" onClick={() => setIsCreateModalOpen(true)}>
              Add API key
            </button>
          </div>
        </div>

        <div className="mt-5 space-y-4">
            {apiKeys.map((apiKey) => (
              <div key={apiKey.id} className="surface-muted p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h3 className="font-display text-lg text-sand">{apiKey.name}</h3>
                    <p className="mt-1 text-xs uppercase tracking-[0.18em] text-sand/45">{formatLastUsed(apiKey.last_used_at)}</p>
                  </div>
                  <button
                    className="btn-danger px-3 py-2 text-sm font-semibold"
                    type="button"
                    onClick={() => void handleRevokeApiKey(apiKey.id)}
                    disabled={revokingKeyId === apiKey.id}
                  >
                    {revokingKeyId === apiKey.id ? "Revoking..." : "Revoke"}
                  </button>
                </div>
              </div>
            ))}
            {isLoadingKeys ? <p className="surface-muted px-4 py-6 text-sm text-sand/60">Loading API keys...</p> : null}
            {!isLoadingKeys && apiKeys.length === 0 ? (
              <div className=" border border-dashed border-white/15 bg-white/5 px-5 py-8 text-center">
                <h3 className="font-display text-lg text-sand">No API keys yet</h3>
                <p className="mt-2 text-sm text-sand/60">Create your first key to get started!</p>
              </div>
            ) : null}
        </div>
      </article>

      <Modal open={isCreateModalOpen} onClose={closeCreateModal} labelledBy="api-key-create-title" panelClassName="max-w-lg">
        <article className="p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 id="api-key-create-title" className="font-display text-2xl">Add API key</h2>
            <button className="btn-secondary px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={closeCreateModal}>
              Close
            </button>
          </div>

          {!latestApiKey ? (
            <form className="mt-5 grid gap-4" onSubmit={handleCreateApiKey}>
              <label className="grid gap-2 text-sm text-sand/70">
                <span className="font-semibold text-sand">Key name</span>
                <input
                  className="field px-4 py-3 text-sm outline-none transition focus:border-white/25"
                  value={newKeyName}
                  onChange={(event) => setNewKeyName(event.target.value)}
                  placeholder="Desktop client"
                  maxLength={80}
                  autoFocus
                />
              </label>
              <div>
                <button
                  className=" bg-sand px-4 py-3 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60"
                  type="submit"
                  disabled={isCreatingKey || !newKeyName.trim()}
                >
                  {isCreatingKey ? "Creating..." : "Create API key"}
                </button>
              </div>
            </form>
          ) : (
            <div className="mt-5 grid gap-4">
              <div className="break-all  bg-black px-4 py-3 font-mono text-sm text-white">
                {latestApiKey}
              </div>
              <div className="flex items-center gap-3">
                <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas" type="button" onClick={() => void handleCopyLatestApiKey()}>
                  Copy key
                </button>
              </div>
            </div>
          )}
        </article>
      </Modal>

      <Modal open={isApiInfoModalOpen} onClose={closeApiInfoModal} labelledBy="api-info-title" panelClassName="max-w-2xl">
        <article className="p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 id="api-info-title" className="font-display text-2xl">API info</h2>
            <button className="btn-secondary px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={closeApiInfoModal}>
              Close
            </button>
          </div>

          <div className="mt-5 space-y-6">
            <div>
              <h3 className="font-display text-lg text-sand">Base URL</h3>
              <div className="mt-2 flex items-center gap-3">
                <code className="surface-muted px-3 py-2 text-sm font-mono text-sand">{API_V1_BASE_URL}</code>
              </div>
            </div>
            <div>
              <h3 className="font-display text-lg text-sand">Chat completions</h3>
              <div className="mt-2 flex items-center gap-3">
                <code className="surface-muted px-3 py-2 text-sm font-mono text-sand">{API_V1_BASE_URL}/chat/completions</code>
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display text-lg text-sand">Token usage</h3>
                <ApiUrlInfoButton
                  label="Token usage endpoint details"
                  open={openInfoId === "usage"}
                  onToggle={() => toggleInfo("usage")}
                />
              </div>
              <div className="mt-2 flex items-center gap-3">
                <code className="surface-muted px-3 py-2 text-sm font-mono text-sand">{`${API_V1_BASE_URL}/usage/{60m|24h|7d|30d}`}</code>
              </div>
              {openInfoId === "usage" ? (
                <div className="surface-muted mt-3 space-y-3 px-4 py-3 text-sm text-sand/70">
                  <p>
                    Returns the total tokens used by the API key in the Authorization header for the selected
                    timeframe. Replace the path segment with <code className="font-mono text-sand">60m</code>,{" "}
                    <code className="font-mono text-sand">24h</code>, <code className="font-mono text-sand">7d</code>, or{" "}
                    <code className="font-mono text-sand">30d</code>.
                  </p>
                  <pre className="overflow-x-auto bg-black/40 px-3 py-3 font-mono text-xs text-sand">{`curl -k ${API_V1_BASE_URL}/usage/24h \\
  -H "Authorization: Bearer API_KEY"`}</pre>
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-[0.18em] text-sand/45">Example response</p>
                    <pre className="overflow-x-auto bg-black/40 px-3 py-3 font-mono text-xs text-sand">{JSON.stringify(
                        {
                          object: "usage",
                          timeframe: "24h",
                          total_tokens: 12345,
                        },
                        null,
                        2,
                      )}</pre>
                  </div>
                </div>
              ) : null}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display text-lg text-sand">List models</h3>
                <ApiUrlInfoButton
                  label="List models endpoint details"
                  open={openInfoId === "models"}
                  onToggle={() => toggleInfo("models")}
                />
              </div>
              <div className="mt-2 flex items-center gap-3">
                <code className="surface-muted px-3 py-2 text-sm font-mono text-sand">{API_V1_BASE_URL}/models</code>
              </div>
              {openInfoId === "models" ? (
                <div className="surface-muted mt-3 space-y-3 px-4 py-3 text-sm text-sand/70">
                  <p>
                    Returns currently enabled models in OpenAI-compatible format. Use a model{" "}
                    <code className="font-mono text-sand">id</code> from this list as the{" "}
                    <code className="font-mono text-sand">model</code> field in chat completions.
                  </p>
                  <pre className="overflow-x-auto bg-black/40 px-3 py-3 font-mono text-xs text-sand">{`curl -k ${API_V1_BASE_URL}/models`}</pre>
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-[0.18em] text-sand/45">Example response</p>
                    {isLoadingV1Models ? (
                      <p className="text-sm text-sand/60">Loading models...</p>
                    ) : (
                      <pre className="overflow-x-auto bg-black/40 px-3 py-3 font-mono text-xs text-sand">
                        {JSON.stringify(buildModelsExampleResponse(v1Models), null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </article>
      </Modal>
    </section>
  );
}
