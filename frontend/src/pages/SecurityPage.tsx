import { useEffect, useRef, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { AppSettingsRecord } from "../lib/records";
import SettingsLayout from "./SettingsLayout";

const DEFAULT_SITENAME = "LmPanel";

export default function SecurityPage() {
  const { token, refreshPublicSettings } = useAuth();
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
    brute_force_enabled: true,
    brute_force_max_failures: 10,
    brute_force_window_minutes: 15,
    brute_force_block_minutes: 15,
  });
  const [localSiteKey, setLocalSiteKey] = useState("");
  const [localSecretKey, setLocalSecretKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<keyof AppSettingsRecord | null>(null);

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

  const prevHasKeysRef = useRef(false);

  useEffect(() => {
    const prev = prevHasKeysRef.current;
    if (prev && !hasTurnstileKeys && settings.cloudflare_turnstile_enabled) {
      void updateSetting("cloudflare_turnstile_enabled", false);
    } else if (!prev && hasTurnstileKeys && !settings.cloudflare_turnstile_enabled) {
      void updateSetting("cloudflare_turnstile_enabled", true);
    }
    prevHasKeysRef.current = hasTurnstileKeys;
  }, [hasTurnstileKeys]);

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

  async function updateSetting(settingName: keyof AppSettingsRecord, nextValue: boolean | string | number) {
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
    <SettingsLayout title="Security">
      <section className="grid gap-4">
      <article>
        <h2 className="font-display text-xl">Security</h2>

        <div className="mt-5 grid gap-3">
          <div className="surface-muted py-4 px-4">
            <div className="text-sm font-semibold text-sand">CAPTCHA</div>
            <p className="mt-1 text-sm text-sand/65">
              Enable Cloudflare Turnstile to protect login and registration from automated submissions.
            </p>

            <div className="mt-4 grid gap-3">
              <label className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-sand">Enable CAPTCHA</div>
                  <p className="mt-1 text-sm text-sand/65">
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
                <span className="text-sm font-semibold text-sand">Site Key</span>
                <p className="text-sm text-sand/65">
                  {settings.cloudflare_turnstile_site_key
                    ? "Enter a new value to replace the saved site key, or leave blank to remove it."
                    : "Enter your Cloudflare Turnstile site key."}
                </p>
                <input
                  type="text"
                  className="max-w-md  field px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
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

              <label className="grid gap-2">
                <span className="text-sm font-semibold text-sand">Secret Key</span>
                <p className="text-sm text-sand/65">
                  {settings.cloudflare_turnstile_secret_key_set
                    ? "Enter a new value to replace the saved secret key, or leave blank to remove it."
                    : "Enter your Cloudflare Turnstile secret key."}
                </p>
                <input
                  type="password"
                  className="max-w-md  field px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                  value={localSecretKey}
                  onChange={(e) => setLocalSecretKey(e.target.value)}
                  onBlur={() => {
                    if (localSecretKey.trim() !== "••••••••") {
                      void updateTurnstileSecretKey(localSecretKey.trim());
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      if (localSecretKey.trim() !== "••••••••") {
                        void updateTurnstileSecretKey(localSecretKey.trim());
                      }
                    }
                  }}
                  disabled={isLoading || isSaving === "cloudflare_turnstile_secret_key_set"}
                  autoComplete="off"
                  placeholder={settings.cloudflare_turnstile_secret_key_set ? "••••••••" : "Cloudflare Turnstile secret key"}
                />
              </label>

              {isCheckboxDisabled && !settings.cloudflare_turnstile_enabled ? (
                <p className="text-sm text-amber-900/80">Enable CAPTCHA only after filling in both the Site Key and Secret Key.</p>
              ) : null}
            </div>
          </div>

          <div className="surface-muted py-4 px-4">
            <div className="text-sm font-semibold text-sand">Brute Force Protection</div>
            <p className="mt-1 text-sm text-sand/65">
              Automatically block IP addresses after repeated failed login attempts to prevent brute force attacks.
            </p>

            <div className="mt-4 grid gap-3">
              <label className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-sand">Enable Brute Force Protection</div>
                  <p className="mt-1 text-sm text-sand/65">
                    {settings.brute_force_enabled
                      ? "Brute force protection is enabled."
                      : "Block sources after repeated failed authentication attempts."}
                  </p>
                </div>
                <input
                  type="checkbox"
                  checked={settings.brute_force_enabled}
                  disabled={isLoading || isSaving === "brute_force_enabled"}
                  onChange={(event) => void updateSetting("brute_force_enabled", event.target.checked)}
                />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Max Failed Attempts</span>
                  <p className="text-sm text-sand/65">
                    Block after this many failed attempts within the time window.
                  </p>
                  <select
                    className="max-w-xs field px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={settings.brute_force_max_failures}
                    onChange={(e) => void updateSetting("brute_force_max_failures", Number(e.target.value))}
                    disabled={isLoading || isSaving === "brute_force_max_failures" || !settings.brute_force_enabled}
                  >
                    <option value={10}>10</option>
                    <option value={100}>100</option>
                  </select>
                </label>

                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Time Window</span>
                  <p className="text-sm text-sand/65">
                    Count failures within this time period.
                  </p>
                  <select
                    className="max-w-xs field px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={settings.brute_force_window_minutes}
                    onChange={(e) => void updateSetting("brute_force_window_minutes", Number(e.target.value))}
                    disabled={isLoading || isSaving === "brute_force_window_minutes" || !settings.brute_force_enabled}
                  >
                    <option value={1}>1 minute</option>
                    <option value={5}>5 minutes</option>
                    <option value={15}>15 minutes</option>
                    <option value={60}>1 hour</option>
                  </select>
                </label>
              </div>

              <label className="grid gap-2">
                <span className="text-sm font-semibold text-sand">Block Duration</span>
                <p className="text-sm text-sand/65">
                  How long the source is blocked after exceeding the failure threshold.
                </p>
                <select
                  className="max-w-xs field px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                  value={settings.brute_force_block_minutes}
                  onChange={(e) => void updateSetting("brute_force_block_minutes", Number(e.target.value))}
                  disabled={isLoading || isSaving === "brute_force_block_minutes" || !settings.brute_force_enabled}
                >
                  <option value={15}>15 minutes</option>
                  <option value={60}>1 hour</option>
                  <option value={1440}>24 hours</option>
                </select>
              </label>
            </div>
          </div>

          <div className="surface-muted py-4 px-4">
            <div className="text-sm font-semibold text-sand">2FA</div>
            <p className="mt-1 text-sm text-sand/65">
              Two-factor authentication for user accounts.
            </p>
            <div className="mt-4  field px-4 py-3">
              <p className="text-sm text-sand/65">Coming soon...</p>
            </div>
          </div>
        </div>
      </article>
      </section>
    </SettingsLayout>
  );
}
