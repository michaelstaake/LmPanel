import { FormEvent, useEffect, useState } from "react";
import Modal from "../components/ui/Modal";
import CodeEditor from "../components/ui/CodeEditor";
import { apiDelete, apiGet, apiPost, fetchV1Models, type V1ModelEntry } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { ApiKeyCreateResponse, ApiKeyRecord } from "../lib/records";

const MINUTE_IN_MS = 60 * 1000;
const HOUR_IN_MS = 60 * MINUTE_IN_MS;
const DAY_IN_MS = 24 * HOUR_IN_MS;

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

function isDefaultThinkingDisabled(model: V1ModelEntry): boolean {
  if (model.discourage_thinking) {
    return true;
  }
  const capability = model.thinking_capability ?? "none";
  if (capability === "always") {
    return false;
  }
  if (capability === "none") {
    return true;
  }
  return model.default_thinking_enabled === false;
}

export default function ApiPage() {
  const { token, user, setupStatus } = useAuth();
  const { showError, showSuccess } = useToast();
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [latestApiKey, setLatestApiKey] = useState("");
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isLoadingKeys, setIsLoadingKeys] = useState(false);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [revokingKeyId, setRevokingKeyId] = useState<number | null>(null);
  const [v1Models, setV1Models] = useState<V1ModelEntry[]>([]);
  const [isLoadingV1Models, setIsLoadingV1Models] = useState(false);
  const [opencodeConfig, setOpencodeConfig] = useState("");

  useEffect(() => {
    if (!token || !user) {
      setApiKeys([]);
      setV1Models([]);
      setOpencodeConfig("");
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

  const DEFAULT_API_BASE_URL = "https://EXAMPLE.PUP:8443";

  const BASE_URL = setupStatus?.api_base_url || import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;

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

  function buildOpencodeConfig(): string {
    const models: Record<string, unknown> = {};
    for (const model of v1Models) {
      const entry: Record<string, unknown> = { name: model.id };
      if (model.vision_enabled) {
        entry.capabilities = { vision: true, image_input: true };
      }
      if (isDefaultThinkingDisabled(model)) {
        entry.options = { reasoning: { enabled: false } };
      }
      models[model.id] = entry;
    }

    const config = {
      $schema: "https://opencode.ai/config.json",
      provider: {
        lmpanel: {
          name: "lmpanel",
          npm: "@ai-sdk/openai-compatible",
          options: {
            baseURL: `${BASE_URL}/v1`,
            apiKey: "API_KEY",
            timeout: 7200000,
          },
          models,
        },
      },
    };

    return JSON.stringify(config, null, 2);
  }

  useEffect(() => {
    setOpencodeConfig(buildOpencodeConfig());
  }, [v1Models, BASE_URL]);

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
    <section className="grid gap-0">
      <article className=" border border-black/10 bg-white/85 p-5 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <h2 className="font-display text-2xl">API Keys</h2>
          </div>
          <button className=" border border-black/15 bg-white px-4 py-3 text-sm font-semibold text-black transition hover:bg-black/5" type="button" onClick={() => setIsCreateModalOpen(true)}>
            Add API key
          </button>
        </div>

        <div className="mt-5 space-y-4">
            {apiKeys.map((apiKey) => (
              <div key={apiKey.id} className=" border border-black/10 bg-[#fffdf7] p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h3 className="font-display text-lg text-black">{apiKey.name}</h3>
                    <p className="mt-1 text-xs uppercase tracking-[0.18em] text-black/45">{formatLastUsed(apiKey.last_used_at)}</p>
                  </div>
                  <button
                    className=" border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                    type="button"
                    onClick={() => void handleRevokeApiKey(apiKey.id)}
                    disabled={revokingKeyId === apiKey.id}
                  >
                    {revokingKeyId === apiKey.id ? "Revoking..." : "Revoke"}
                  </button>
                </div>
              </div>
            ))}
            {isLoadingKeys ? <p className=" border border-black/10 bg-white px-4 py-6 text-sm text-black/60">Loading API keys...</p> : null}
            {!isLoadingKeys && apiKeys.length === 0 ? (
              <div className=" border border-dashed border-black/15 bg-sand/60 px-5 py-8 text-center">
                <h3 className="font-display text-lg text-black">No API keys yet</h3>
                <p className="mt-2 text-sm text-black/60">Create your first key to get started!</p>
              </div>
            ) : null}
        </div>
      </article>

      <Modal open={isCreateModalOpen} onClose={closeCreateModal} labelledBy="api-key-create-title" panelClassName="max-w-lg">
        <article className="p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 id="api-key-create-title" className="font-display text-2xl">Add API key</h2>
            <button className=" border border-black/15 bg-white px-4 py-2 text-sm font-semibold text-black" type="button" onClick={closeCreateModal}>
              Close
            </button>
          </div>

          {!latestApiKey ? (
            <form className="mt-5 grid gap-4" onSubmit={handleCreateApiKey}>
              <label className="grid gap-2 text-sm text-black/70">
                <span className="font-semibold text-black">Key name</span>
                <input
                  className=" border border-black/10 bg-white px-4 py-3 text-sm outline-none transition focus:border-black/25"
                  value={newKeyName}
                  onChange={(event) => setNewKeyName(event.target.value)}
                  placeholder="Desktop client"
                  maxLength={80}
                  autoFocus
                />
              </label>
              <div>
                <button
                  className=" bg-ink px-4 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
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
                <button className=" bg-ink px-4 py-2 text-sm font-semibold text-white" type="button" onClick={() => void handleCopyLatestApiKey()}>
                  Copy key
                </button>
              </div>
            </div>
          )}
        </article>
      </Modal>

      <article className=" border border-black/10 bg-white/85 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-2xl">API Documentation</h2>
        <div className="mt-5 space-y-6">
          <div>
            <h3 className="font-display text-lg text-black">Base URL</h3>
            <div className="mt-2 flex items-center gap-3">
              <code className=" border border-black/10 bg-[#fffdf7] px-3 py-2 text-sm font-mono text-black">{BASE_URL}</code>
            </div>
          </div>
          <div>
            <h3 className="font-display text-lg text-black">Chat completions</h3>
            <div className="mt-2 flex items-center gap-3">
              <code className=" border border-black/10 bg-[#fffdf7] px-3 py-2 text-sm font-mono text-black">{BASE_URL}/v1/chat/completions</code>
            </div>
          </div>
          <div>
            <h3 className="font-display text-lg text-black">List models</h3>
            <div className="mt-2 flex items-center gap-3">
              <code className=" border border-black/10 bg-[#fffdf7] px-3 py-2 text-sm font-mono text-black">{BASE_URL}/v1/models</code>
            </div>
          </div>
          <div>
            <h3 className="font-display text-lg text-black">Enabled models</h3>
            {isLoadingV1Models ? (
              <p className="mt-2 text-sm text-black/60">Loading models...</p>
            ) : v1Models.length === 0 ? (
              <p className="mt-2 text-sm text-black/60">No models are currently enabled.</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {v1Models.map((model) => (
                  <li key={model.id} className=" border border-black/10 bg-[#fffdf7] px-3 py-2">
                    <span className="text-sm font-mono text-black">{model.id}</span>
                    {model.description && (
                      <span className="ml-2 text-xs text-black/45">- {model.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </article>

      <article className=" border border-black/10 bg-white/85 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-2xl">OpenCode config</h2>
        <p className="mt-2 text-sm text-black/60">
          Use this in your OpenCode config file to connect to LmPanel's OpenAI-compatible endpoint. Adjust the models and settings as needed.
        </p>
        <div className="mt-4">
          {isLoadingV1Models ? (
            <p className="mt-2 text-sm text-black/60">Loading models...</p>
          ) : (
            <CodeEditor
              value={opencodeConfig}
              onChange={() => {}}
              language="json"
              height="26rem"
            />
          )}
        </div>
      </article>
    </section>
  );
}