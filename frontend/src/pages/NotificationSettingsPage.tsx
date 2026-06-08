import { useEffect, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import SettingsLayout from "./SettingsLayout";

type NotificationSetting = {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
};

const defaultNotificationSettings: NotificationSetting[] = [
  { id: "server_errors", label: "Server Errors", description: "Receive an alert when a Device or Model error occurs", enabled: false },
  { id: "ip_blocked", label: "IP Blocked", description: "Receive an alert when an IP is blocked by brute force protection", enabled: false },
  { id: "user_login", label: "User Login", description: "Receive an alert when a user logs in", enabled: false },
  { id: "user_registers", label: "User Registers", description: "Receive an alert when a user creates an account", enabled: false },
  { id: "usage_limit_reached", label: "Usage Limit Reached", description: "Receive an alert when a user reaches any applicable token or tool usage limit", enabled: false },
];

export default function NotificationSettingsPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [notificationSettings, setNotificationSettings] = useState<NotificationSetting[]>(defaultNotificationSettings);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    void loadSettings(token);
  }, [token]);

  async function loadSettings(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<Record<string, any>>("/api/admin/settings", activeToken);
      const enabled = response.notifications_enabled ?? false;
      setNotificationsEnabled(enabled);

      const settings = [...defaultNotificationSettings];
      for (const setting of settings) {
        const value = response[`notification_${setting.id}_enabled`];
        if (value !== undefined) {
          setting.enabled = value;
        }
      }
      setNotificationSettings(settings);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load notification settings");
    } finally {
      setIsLoading(false);
    }
  }

  async function updateMasterToggle(enabled: boolean) {
    if (!token) return;

    const previousValue = notificationsEnabled;
    setNotificationsEnabled(enabled);

    if (!enabled) {
      const previousSettings = [...notificationSettings];
      setNotificationSettings(prev => prev.map(s => ({ ...s, enabled: false })));

      setIsSaving("master");
      try {
        const updates: Record<string, boolean> = { notifications_enabled: false };
        for (const setting of notificationSettings) {
          updates[`notification_${setting.id}_enabled`] = false;
        }
        await apiPatch("/api/admin/settings", updates, token);
        showSuccess("Notification settings updated.");
      } catch (error) {
        setNotificationsEnabled(previousValue);
        setNotificationSettings(previousSettings);
        showError(error instanceof Error ? error.message : "Failed to update notification settings");
      } finally {
        setIsSaving(null);
      }
    } else {
      setIsSaving("master");
      try {
        await apiPatch("/api/admin/settings", { notifications_enabled: true }, token);
        showSuccess("Notifications enabled.");
      } catch (error) {
        setNotificationsEnabled(previousValue);
        showError(error instanceof Error ? error.message : "Failed to enable notifications");
      } finally {
        setIsSaving(null);
      }
    }
  }

  async function updateNotificationSetting(settingId: string, enabled: boolean) {
    if (!token || !notificationsEnabled) return;

    const previousSettings = [...notificationSettings];
    setNotificationSettings(prev => prev.map(s => s.id === settingId ? { ...s, enabled } : s));

    setIsSaving(settingId);
    try {
      await apiPatch(`/api/admin/settings`, { [`notification_${settingId}_enabled`]: enabled }, token);
      showSuccess("Notification setting updated.");
    } catch (error) {
      setNotificationSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update notification setting");
    } finally {
      setIsSaving(null);
    }
  }

  return (
    <SettingsLayout title="Notifications">
      <section className="grid gap-4">
        <article>
          <h2 className="font-display text-xl">Notifications</h2>
          <p className="mt-1 text-sm text-sand/65">
            Configure how you receive alerts and notifications from LmPanel.
          </p>

          <div className="mt-5 grid gap-3">
            <div className="surface-muted py-4 px-4">
              <label className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-sand">All Notifications</div>
                  <p className="mt-1 text-sm text-sand/65">
                    Master toggle for all notifications. When disabled, all notification types are turned off.
                  </p>
                </div>
                <input
                  type="checkbox"
                  checked={notificationsEnabled}
                  disabled={isLoading || isSaving === "master"}
                  onChange={(event) => void updateMasterToggle(event.target.checked)}
                />
              </label>
            </div>

            {defaultNotificationSettings.map((setting) => (
              <div
                key={setting.id}
                className={`surface-muted py-4 px-4 ${(!notificationsEnabled || isSaving === setting.id) ? "opacity-50 pointer-events-none" : ""}`}
              >
                <label className="flex items-start justify-between gap-4 cursor-pointer">
                  <div>
                    <div className="text-sm font-semibold text-sand">{setting.label}</div>
                    <p className="mt-1 text-sm text-sand/65">{setting.description}</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={notificationsEnabled ? setting.enabled : false}
                    disabled={!notificationsEnabled || isLoading || isSaving === setting.id}
                    onChange={(event) => void updateNotificationSetting(setting.id, event.target.checked)}
                  />
                </label>
              </div>
            ))}
          </div>
        </article>
      </section>
    </SettingsLayout>
  );
}
