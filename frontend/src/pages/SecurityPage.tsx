import { useEffect, useRef, useState } from "react";
import { apiGet, apiPatch, checkForUpdates, UpdateCheckRecord } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { AppSettingsRecord } from "../lib/records";

const DEFAULT_SITENAME = "LmPanel";

export default function SecurityPage() {
  const { token, refreshPublicSettings } = useAuth();
  const { showError, showSuccess } = useToast();
  const [settings, setSettings] = useState<AppSettingsRecord>({
    users_can_register: false,
    sitename: DEFAULT_SITENAME,
    background_color: "#efe8d2",
    background_image_path: null,
    background_image_mode: "fill",
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
  const [localSiteKey, setLocalSiteKey] = useState("");
  const [localSecretKey, setLocalSecretKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<keyof AppSettingsRecord | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateCheckRecord | null>(null);
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);
  const checkIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    void loadSettings(token);
  }, [token]);

  useEffect(() => {
    if (settings.cloudflare_turnstile_site_key) {
      setLocalSiteKey(settings.cloudflare_turnstile_site_key);
    }
  }, [settings.cloudflare_turnstile_site_key]);

  useEffect(() => {
    if (settings.cloudflare_turnstile_secret_key_set) {
      setLocalSecretKey("••••••••");
    }
  }, [settings.cloudflare_turnstile_secret_key_set]);

  useEffect(() => {
    if (!token) return;
    void checkForUpdatesToken(token);
  }, [token]);

  useEffect(() => {
    if (checkIntervalRef.current) {
      clearInterval(checkIntervalRef.current);
      checkIntervalRef.current = null;
    }

    if (token && settings.update_check_mode !== "disabled") {
      checkIntervalRef.current = setInterval(() => {
        if (token) {
          void checkForUpdatesToken(token);
        }
      }, 24 * 60 * 60 * 1000);
    }

    return () => {
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
    };
  }, [token, settings.update_check_mode]);

  async function loadSettings(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<AppSettingsRecord>("/api/admin/settings", activeToken);
      setSettings(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load security settings");
    } finally {
      setIsLoading(false);
    }
  }

  async function checkForUpdatesToken(activeToken: string) {
    try {
      const response = await checkForUpdates(activeToken);
      setUpdateStatus(response);
    } catch {
      // Silently fail - update check is not critical
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
      showSuccess("Security settings updated.");
    } catch (error) {
      setSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update security setting");
    } finally {
      setIsSaving(null);
    }
  }

  async function updateTurnstileSiteKey(nextValue: string) {
    if (!token) {
      return;
    }

    const previousSettings = settings;
    setSettings({ ...settings, cloudflare_turnstile_site_key: nextValue });
    setIsSaving("cloudflare_turnstile_site_key");

    try {
      const response = await apiPatch<{ cloudflare_turnstile_site_key: string }, AppSettingsRecord>("/api/admin/settings", { cloudflare_turnstile_site_key: nextValue }, token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Security settings updated.");
    } catch (error) {
      setSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update security setting");
    } finally {
      setIsSaving(null);
    }
  }

  async function updateTurnstileSecretKey(nextValue: string) {
    if (!token) {
      return;
    }

    const previousSettings = settings;
    setSettings({ ...settings, cloudflare_turnstile_secret_key_set: nextValue !== "" });
    setIsSaving("cloudflare_turnstile_secret_key_set");

    try {
      const response = await apiPatch<{ cloudflare_turnstile_secret_key: string }, AppSettingsRecord>("/api/admin/settings", { cloudflare_turnstile_secret_key: nextValue }, token);
      setSettings(response);
      await refreshPublicSettings();
      showSuccess("Security settings updated.");
    } catch (error) {
      setSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update security setting");
    } finally {
      setIsSaving(null);
    }
  }

  const hasTurnstileKeys = Boolean(localSiteKey.trim()) && Boolean(settings.cloudflare_turnstile_secret_key_set);
  const canDisableTurnstile = settings.cloudflare_turnstile_enabled;
  const isCheckboxDisabled = isLoading || isSaving === "cloudflare_turnstile_enabled" || (!canDisableTurnstile && !hasTurnstileKeys);

  return (
    <section className="grid gap-4">
      <article className="rounded-2xl border border-black/10 bg-white/80 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-xl">Update check</h2>

        <div className="mt-5 grid gap-3">
          <div className="rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="text-sm font-semibold text-black">Update check mode</div>
            <p className="mt-1 text-sm text-black/65">
              Choose how the app checks for updates. Development checks the latest commit, release checks the latest GitHub release version.
            </p>

            <div className="mt-4 grid gap-3">
              <label className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-black">Update check mode</div>
                  <p className="mt-1 text-sm text-black/65">
                    {settings.update_check_mode === "disabled"
                      ? "Updates are not checked automatically."
                      : settings.update_check_mode === "development"
                        ? "Checking for new commits on the main branch."
                        : "Checking for new GitHub releases."}
                  </p>
                </div>
                <select
                  value={settings.update_check_mode}
                  disabled={isLoading || isSaving === "update_check_mode"}
                  onChange={(event) => void updateSetting("update_check_mode", event.target.value)}
                  className="rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                >
                  <option value="disabled">Disabled</option>
                  <option value="development">Development</option>
                  <option value="release">Release</option>
                </select>
              </label>

              {settings.update_check_mode !== "disabled" && updateStatus && (
                <div className="rounded-xl border border-black/10 bg-white px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold text-black">
                        {updateStatus.update_available ? "Update available" : "Up to date"}
                      </div>
                      <p className="mt-1 text-sm text-black/65">
                        {settings.update_check_mode === "development"
                          ? `Latest commit: ${updateStatus.latest_commit}`
                          : `Latest version: ${updateStatus.latest_version}`}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-60"
                      onClick={() => {
                        if (!token) return;
                        setIsCheckingUpdate(true);
                        void (async () => {
                          try {
                            await checkForUpdatesToken(token);
                          } finally {
                            setIsCheckingUpdate(false);
                          }
                        })();
                      }}
                      disabled={isCheckingUpdate}
                    >
                      {isCheckingUpdate ? "Checking..." : "Check now"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </article>

      <article className="rounded-2xl border border-black/10 bg-white/80 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-xl">Security</h2>

        <div className="mt-5 grid gap-3">
          <div className="rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="text-sm font-semibold text-black">CAPTCHA</div>
            <p className="mt-1 text-sm text-black/65">
              Enable Cloudflare Turnstile to protect login and registration from automated submissions.
            </p>

            <div className="mt-4 grid gap-3">
              <label className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-black">Enable CAPTCHA</div>
                  <p className="mt-1 text-sm text-black/65">
                    {settings.cloudflare_turnstile_enabled
                      ? "CAPTCHA is enabled. Disable to remove the verification step."
                      : "Require CAPTCHA verification on login and registration."}
                  </p>
                </div>
                <input
                  type="checkbox"
                  checked={settings.cloudflare_turnstile_enabled}
                  disabled={isCheckboxDisabled}
                  onChange={(event) => void updateSetting("cloudflare_turnstile_enabled", event.target.checked)}
                />
              </label>

              <label className="grid gap-2">
                <span className="text-sm font-semibold text-black">Site Key</span>
                <p className="text-sm text-black/65">
                  {settings.cloudflare_turnstile_site_key
                    ? "A site key is saved. Enter a new value to replace it, or clear it below."
                    : "Enter your Cloudflare Turnstile site key."}
                </p>
                <input
                  type="text"
                  className="max-w-md rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                  value={localSiteKey}
                  onChange={(e) => setLocalSiteKey(e.target.value)}
                  onBlur={() => {
                    if (localSiteKey.trim() !== (settings.cloudflare_turnstile_site_key || "")) {
                      void updateTurnstileSiteKey(localSiteKey.trim());
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      if (localSiteKey.trim() !== (settings.cloudflare_turnstile_site_key || "")) {
                        void updateTurnstileSiteKey(localSiteKey.trim());
                      }
                    }
                  }}
                  disabled={isLoading || isSaving === "cloudflare_turnstile_site_key"}
                  placeholder="1x00000000000000000000AA"
                />
              </label>

              {settings.cloudflare_turnstile_site_key ? (
                <button
                  type="button"
                  className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => {
                    if (!token) return;
                    void (async () => {
                      setIsSaving("cloudflare_turnstile_site_key");
                      try {
                        const response = await apiPatch<{ cloudflare_turnstile_site_key: string }, AppSettingsRecord>(
                          "/api/admin/settings",
                          { cloudflare_turnstile_site_key: "" },
                          token,
                        );
                        setSettings(response);
                        setLocalSiteKey("");
                        await refreshPublicSettings();
                        showSuccess("Site key removed.");
                      } catch (error) {
                        showError(error instanceof Error ? error.message : "Failed to clear site key");
                      } finally {
                        setIsSaving(null);
                      }
                    })();
                  }}
                  disabled={isLoading || isSaving === "cloudflare_turnstile_site_key"}
                >
                  Clear site key
                </button>
              ) : null}

              <label className="grid gap-2">
                <span className="text-sm font-semibold text-black">Secret Key</span>
                <p className="text-sm text-black/65">
                  {settings.cloudflare_turnstile_secret_key_set
                    ? "A secret key is saved. Enter a new value to replace it, or clear it below."
                    : "Enter your Cloudflare Turnstile secret key."}
                </p>
                <input
                  type="password"
                  className="max-w-md rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                  value={localSecretKey}
                  onChange={(e) => setLocalSecretKey(e.target.value)}
                  onBlur={() => {
                    if (localSecretKey.trim() !== "••••••••" && localSecretKey.trim() !== "") {
                      void updateTurnstileSecretKey(localSecretKey.trim());
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      if (localSecretKey.trim() !== "••••••••" && localSecretKey.trim() !== "") {
                        void updateTurnstileSecretKey(localSecretKey.trim());
                      }
                    }
                  }}
                  disabled={isLoading || isSaving === "cloudflare_turnstile_secret_key_set"}
                  autoComplete="off"
                  placeholder={settings.cloudflare_turnstile_secret_key_set ? "••••••••" : "Cloudflare Turnstile secret key"}
                />
              </label>

              {settings.cloudflare_turnstile_secret_key_set ? (
                <button
                  type="button"
                  className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => {
                    if (!token) return;
                    void (async () => {
                      setIsSaving("cloudflare_turnstile_secret_key_set");
                      try {
                        const response = await apiPatch<{ cloudflare_turnstile_secret_key: string }, AppSettingsRecord>(
                          "/api/admin/settings",
                          { cloudflare_turnstile_secret_key: "" },
                          token,
                        );
                        setSettings(response);
                        setLocalSecretKey("");
                        await refreshPublicSettings();
                        showSuccess("Secret key removed.");
                      } catch (error) {
                        showError(error instanceof Error ? error.message : "Failed to clear secret key");
                      } finally {
                        setIsSaving(null);
                      }
                    })();
                  }}
                  disabled={isLoading || isSaving === "cloudflare_turnstile_secret_key_set"}
                >
                  Clear secret key
                </button>
              ) : null}

              {isCheckboxDisabled && !settings.cloudflare_turnstile_enabled ? (
                <p className="text-sm text-amber-900/80">Enable CAPTCHA only after filling in both the Site Key and Secret Key.</p>
              ) : null}
            </div>
          </div>

          <div className="rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="text-sm font-semibold text-black">2FA</div>
            <p className="mt-1 text-sm text-black/65">
              Two-factor authentication for user accounts.
            </p>
            <div className="mt-4 rounded-xl border border-black/10 bg-white px-4 py-3">
              <p className="text-sm text-black/65">Coming soon...</p>
            </div>
          </div>
        </div>
      </article>
    </section>
  );
}
