import { useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPostForm, resolveApiUrl } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { AppSettingsRecord } from "../lib/records";
import SettingsLayout from "./SettingsLayout";

const DEFAULT_SITENAME = "LmPanel";
const ALLOWED_FAVICON_TYPES = new Set(["image/jpeg", "image/png"]);
const MAX_FAVICON_BYTES = 2 * 1024 * 1024;

function normalizePublicUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return "";
  }

  if (trimmed.endsWith("/")) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "https:") {
      return null;
    }
    if (parsed.username || parsed.password || parsed.port) {
      return null;
    }
    if (parsed.pathname !== "" && parsed.pathname !== "/") {
      return null;
    }
    if (parsed.search || parsed.hash) {
      return null;
    }
    if (!parsed.hostname) {
      return null;
    }
    return `https://${parsed.hostname}`;
  } catch {
    return null;
  }
}

export default function ConfigurationPage() {
  const { refreshPublicSettings, token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [settings, setSettings] = useState<AppSettingsRecord>({
    users_can_register: false,
    sitename: DEFAULT_SITENAME,
    favicon_path: null,
    input_price_per_1m: 0,
    output_price_per_1m: 0,
    public_url: "",
    cloudflare_turnstile_enabled: false,
    cloudflare_turnstile_site_key: null,
    cloudflare_turnstile_secret_key_set: false,
    two_factor_enabled: false,
    usage_limit_tokens_60_minutes: 0,
    usage_limit_tokens_24_hours: 0,
    usage_limit_tokens_7_days: 0,
    usage_limit_tokens_30_days: 0,
    usage_limit_tools_60_minutes: 0,
    usage_limit_tools_24_hours: 0,
    usage_limit_tools_7_days: 0,
    usage_limit_tools_30_days: 0,
    update_check_mode: "disabled",
  });
  const [localSitename, setLocalSitename] = useState(DEFAULT_SITENAME);
  const [localPublicUrl, setLocalPublicUrl] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<keyof AppSettingsRecord | null>(null);
  const [isUploadingFavicon, setIsUploadingFavicon] = useState(false);
  const faviconInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    void loadSettings(token);
  }, [token]);

  useEffect(() => {
    if (settings.sitename) {
      setLocalSitename(settings.sitename);
    }
  }, [settings.sitename]);

  useEffect(() => {
    setLocalPublicUrl(settings.public_url || "");
  }, [settings.public_url]);

  async function loadSettings(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<AppSettingsRecord>("/api/admin/settings", activeToken);
      setSettings(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load configuration settings");
    } finally {
      setIsLoading(false);
    }
  }

  async function updateSetting(settingName: keyof AppSettingsRecord, nextValue: boolean | string) {
    if (!token) {
      return;
    }

    const previousSettings = settings;
    const nextSettings = { ...settings, [settingName]: nextValue };
    setSettings(nextSettings as AppSettingsRecord);
    setIsSaving(settingName);

    try {
      const response = await apiPatch<Partial<AppSettingsRecord>, AppSettingsRecord>("/api/admin/settings", { [settingName]: nextValue }, token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Configuration updated.");
    } catch (error) {
      setSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update configuration setting");
    } finally {
      setIsSaving(null);
    }
  }

  async function uploadFavicon(file: File) {
    if (!token) {
      return;
    }

    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ALLOWED_FAVICON_TYPES.has(file.type) && !["jpg", "jpeg", "png"].includes(extension)) {
      showError("Favicon must be a JPG or PNG file.");
      return;
    }

    if (file.size > MAX_FAVICON_BYTES) {
      showError("Favicon must be 2 MB or smaller.");
      return;
    }

    setIsUploadingFavicon(true);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await apiPostForm<AppSettingsRecord>("/api/admin/settings/favicon", formData, token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Favicon updated.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to upload favicon");
    } finally {
      setIsUploadingFavicon(false);
      if (faviconInputRef.current) {
        faviconInputRef.current.value = "";
      }
    }
  }

  async function deleteFavicon() {
    if (!token) {
      return;
    }

    setIsUploadingFavicon(true);
    try {
      const response = await apiDelete<AppSettingsRecord>("/api/admin/settings/favicon", token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Favicon removed.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to remove favicon");
    } finally {
      setIsUploadingFavicon(false);
      if (faviconInputRef.current) {
        faviconInputRef.current.value = "";
      }
    }
  }

  function commitSitename(rawSitename: string) {
    const normalized = rawSitename.trim() || DEFAULT_SITENAME;
    setLocalSitename(normalized);

    if (normalized !== settings.sitename) {
      void updateSetting("sitename", normalized);
    }
  }

  function commitPublicUrl(rawUrl: string) {
    const normalized = normalizePublicUrl(rawUrl);
    if (normalized === null) {
      setLocalPublicUrl(settings.public_url || "");
      showError("URL must be https://hostname with no port, path, or trailing slash.");
      return;
    }

    setLocalPublicUrl(normalized);
    if (normalized !== (settings.public_url || "")) {
      void updateSetting("public_url", normalized);
    }
  }

  return (
    <SettingsLayout title="Configuration">
      <section className="grid gap-4">
      <article>
        <h2 className="font-display text-xl text-sand">Configuration</h2>

        <div className="mt-5 grid gap-6">
          <div className="flex flex-col gap-2">
            <div>
              <div className="text-sm font-semibold text-sand">Site name</div>
              <p className="mt-1 text-sm text-sand/65">
                This will update the browser title and the header.
              </p>
            </div>
            <div className="mt-2 max-w-md">
              <input
                type="text"
                className="w-full border border-white/15 bg-white/10 px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                value={localSitename}
                onChange={(e) => setLocalSitename(e.target.value)}
                onBlur={() => commitSitename(localSitename)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    commitSitename(localSitename);
                  }
                }}
                disabled={isLoading || isSaving === "sitename"}
                placeholder="LmPanel"
              />
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <div>
              <div className="text-sm font-semibold text-sand">URL</div>
              <p className="mt-1 text-sm text-sand/65">
                Set the URL to your LmPanel instance. Used in API docs, required for SSL, and otherwise useful.
              </p>
            </div>
            <div className="mt-2 max-w-xl">
              <input
                type="url"
                className="w-full border border-white/15 bg-white/10 px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                value={localPublicUrl}
                onChange={(e) => setLocalPublicUrl(e.target.value)}
                onBlur={() => commitPublicUrl(localPublicUrl)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    commitPublicUrl(localPublicUrl);
                  }
                }}
                disabled={isLoading || isSaving === "public_url"}
                placeholder="https://lmpanel.example.com"
              />
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-sm font-semibold text-sand">Favicon</div>
                <p className="mt-1 text-sm text-sand/65">
                  Upload a square JPG or PNG at least 16px, max 2 MB.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="inline-flex cursor-pointer items-center border border-white/15 bg-white/10 px-3 py-2 text-sm font-semibold text-sand transition hover:bg-white/15">
                  <span>{isUploadingFavicon ? "Uploading..." : "Upload favicon"}</span>
                  <input
                    ref={faviconInputRef}
                    type="file"
                    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                    className="hidden"
                    disabled={isLoading || isUploadingFavicon}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        void uploadFavicon(file);
                      }
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="border border-white/15 bg-white/10 px-3 py-2 text-sm font-semibold text-sand transition hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => void deleteFavicon()}
                  disabled={isLoading || isUploadingFavicon || !settings.favicon_path}
                >
                  Delete favicon
                </button>
              </div>
            </div>
            {settings.favicon_path ? (
              <div className="grid gap-3">
                <p className="text-sm text-sand/65">The uploaded favicon is active across all pages.</p>
                <img
                  src={resolveApiUrl(settings.favicon_path)}
                  alt="Current favicon"
                  className="h-16 w-16 border border-white/15 object-contain"
                />
              </div>
            ) : (
              <p className="text-sm text-sand/65">No favicon uploaded.</p>
            )}
          </div>
          <label className="flex items-start justify-between gap-4">
            <div>
              <div className="text-sm font-semibold text-sand">Users can register</div>
              <p className="mt-1 text-sm text-sand/65">
                If enabled, visitors can create standard accounts for themselves. If disabled, only admins can create users.
              </p>
            </div>
            <input
              type="checkbox"
              checked={settings.users_can_register}
              disabled={isLoading || isSaving === "users_can_register"}
              onChange={(event) => void updateSetting("users_can_register", event.target.checked)}
            />
          </label>
        </div>
      </article>
      </section>
    </SettingsLayout>
  );
}
