import { useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPostForm, resolveApiUrl } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { AppSettingsRecord } from "../lib/records";

const DEFAULT_BACKGROUND_COLOR = "#efe8d2";
const DEFAULT_SITENAME = "LmPanel";
const ALLOWED_BACKGROUND_IMAGE_TYPES = new Set(["image/jpeg", "image/png"]);
const MAX_BACKGROUND_IMAGE_BYTES = 10 * 1024 * 1024;
const HEX_COLOR_PATTERN = /^#[0-9a-f]{6}$/i;

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
    background_color: DEFAULT_BACKGROUND_COLOR,
    background_image_path: null,
    background_image_mode: "fill",
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
  });
  const [localSitename, setLocalSitename] = useState(DEFAULT_SITENAME);
  const [localPublicUrl, setLocalPublicUrl] = useState("");
  const [localBackgroundColor, setLocalBackgroundColor] = useState(DEFAULT_BACKGROUND_COLOR);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<keyof AppSettingsRecord | null>(null);
  const [isUploadingBackgroundImage, setIsUploadingBackgroundImage] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);

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
    setLocalBackgroundColor(settings.background_color || DEFAULT_BACKGROUND_COLOR);
  }, [settings.background_color]);

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

  async function uploadBackgroundImage(file: File) {
    if (!token) {
      return;
    }

    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ALLOWED_BACKGROUND_IMAGE_TYPES.has(file.type) && !["jpg", "jpeg", "png"].includes(extension)) {
      showError("Background image must be a JPG or PNG file.");
      return;
    }

    if (file.size > MAX_BACKGROUND_IMAGE_BYTES) {
      showError("Background image must be 10 MB or smaller.");
      return;
    }

    setIsUploadingBackgroundImage(true);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await apiPostForm<AppSettingsRecord>("/api/admin/settings/background-image", formData, token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Background image updated.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to upload background image");
    } finally {
      setIsUploadingBackgroundImage(false);
      if (uploadInputRef.current) {
        uploadInputRef.current.value = "";
      }
    }
  }

  async function deleteBackgroundImage() {
    if (!token) {
      return;
    }

    setIsUploadingBackgroundImage(true);
    try {
      const response = await apiDelete<AppSettingsRecord>("/api/admin/settings/background-image", token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Background image removed.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to remove background image");
    } finally {
      setIsUploadingBackgroundImage(false);
      if (uploadInputRef.current) {
        uploadInputRef.current.value = "";
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

  function commitBackgroundColor(rawColor: string) {
    const normalized = (rawColor.trim() || DEFAULT_BACKGROUND_COLOR).toLowerCase();
    setLocalBackgroundColor(normalized);

    if (!HEX_COLOR_PATTERN.test(normalized)) {
      setLocalBackgroundColor(settings.background_color || DEFAULT_BACKGROUND_COLOR);
      showError("Background color must be a hex code like #efe8d2.");
      return;
    }

    if (normalized !== settings.background_color) {
      void updateSetting("background_color", normalized);
    }
  }

  return (
    <section className="grid gap-4">
      <article className="rounded-2xl border border-black/10 bg-white/80 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-xl">Configuration</h2>

        <div className="mt-5 grid gap-3">
          <div className="flex flex-col gap-2 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-black">Site name</div>
                <p className="mt-1 text-sm text-black/65">
                  This will update the browser title and the header.
                </p>
              </div>
            </div>
            <div className="mt-2 max-w-md">
              <input
                type="text"
                className="w-full rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
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
          <div className="flex flex-col gap-3 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-black">Background color</div>
                <p className="mt-1 text-sm text-black/65">
                  Used whenever no background image is set, and always on mobile.
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-3 md:flex-row md:items-center">
              <input
                type="color"
                value={localBackgroundColor}
                onChange={(event) => {
                  const nextColor = event.target.value.toLowerCase();
                  setLocalBackgroundColor(nextColor);
                  if (nextColor !== settings.background_color) {
                    void updateSetting("background_color", nextColor);
                  }
                }}
                disabled={isLoading || isSaving === "background_color"}
                className="h-11 w-16 cursor-pointer rounded-xl border border-black/15 bg-white p-1 disabled:cursor-not-allowed"
              />
              <input
                type="text"
                inputMode="text"
                className="w-full max-w-xs rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                value={localBackgroundColor}
                onChange={(event) => setLocalBackgroundColor(event.target.value)}
                onBlur={() => commitBackgroundColor(localBackgroundColor)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    commitBackgroundColor(localBackgroundColor);
                  }
                }}
                disabled={isLoading || isSaving === "background_color"}
                placeholder="#efe8d2"
              />
            </div>
          </div>
          <div className="flex flex-col gap-3 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-sm font-semibold text-black">Background image</div>
                <p className="mt-1 text-sm text-black/65">
                  Applied on desktop only. Upload a JPG or PNG up to 10 MB.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="inline-flex cursor-pointer items-center rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-semibold text-black transition hover:border-black/20 hover:bg-black/5">
                  <span>{isUploadingBackgroundImage ? "Uploading..." : "Upload image"}</span>
                  <input
                    ref={uploadInputRef}
                    type="file"
                    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                    className="hidden"
                    disabled={isLoading || isUploadingBackgroundImage}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        void uploadBackgroundImage(file);
                      }
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-semibold text-black transition hover:border-black/20 hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => void deleteBackgroundImage()}
                  disabled={isLoading || isUploadingBackgroundImage || !settings.background_image_path}
                >
                  Delete image
                </button>
              </div>
            </div>
            <label className="grid gap-2 text-sm text-black/70 md:max-w-xs">
              <span className="font-semibold text-black">Desktop image fit</span>
              <select
                className="rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                value={settings.background_image_mode}
                onChange={(event) => void updateSetting("background_image_mode", event.target.value)}
                disabled={isLoading || isSaving === "background_image_mode"}
              >
                <option value="fill">Fill</option>
                <option value="stretch">Stretch</option>
                <option value="repeat">Repeat</option>
              </select>
            </label>
            {settings.background_image_path ? (
              <div className="grid gap-3">
                <p className="text-sm text-black/65">
                  The uploaded image is active on desktop. Mobile continues to use the background color.
                </p>
                <img
                  src={resolveApiUrl(settings.background_image_path)}
                  alt="Current background"
                  className="h-36 w-full rounded-2xl border border-black/10 bg-white object-cover shadow-sm md:max-w-[220px]"
                />
              </div>
            ) : (
              <p className="text-sm text-black/65">No background image uploaded. Desktop will use the background color until you add one.</p>
            )}
          </div>
          <div className="flex flex-col gap-2 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div>
              <div className="text-sm font-semibold text-black">URL</div>
              <p className="mt-1 text-sm text-black/65">
                Public HTTPS address for this LmPanel instance (no port or trailing slash). Required for Let&apos;s Encrypt on the SSL tab.
              </p>
            </div>
            <div className="mt-2 max-w-xl">
              <input
                type="url"
                className="w-full rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
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
          <label className="flex items-start justify-between gap-4 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div>
              <div className="text-sm font-semibold text-black">Users can register</div>
              <p className="mt-1 text-sm text-black/65">
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

      <article className="rounded-2xl border border-black/10 bg-white/80 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-xl">LmPanel v{__APP_VERSION__}</h2>
        <div className="mt-4 text-sm text-black/65">
          <p className="mt-2">
            Learn more, get help, and contribute on {" "}
            <a
              href="https://github.com/michaelstaake/LmPanel"
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-ink underline underline-offset-2 hover:text-ink/85"
            >
              GitHub
            </a>.
          </p>
        </div>
      </article>
    </section>
  );
}