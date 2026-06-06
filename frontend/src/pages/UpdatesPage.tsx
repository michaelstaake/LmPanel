import { useEffect, useRef, useState } from "react";
import { apiGet, apiPatch, checkForUpdates, UpdateCheckRecord } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { AppSettingsRecord } from "../lib/records";
import SettingsLayout from "./SettingsLayout";

export default function UpdatesPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [settings, setSettings] = useState<AppSettingsRecord>({
    users_can_register: false,
    sitename: "LmPanel",
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
      showError(error instanceof Error ? error.message : "Failed to load settings");
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
      showSuccess("Settings updated.");
    } catch (error) {
      setSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update setting");
    } finally {
      setIsSaving(null);
    }
  }

  return (
    <SettingsLayout title="Updates">
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
    </SettingsLayout>
  );
}
