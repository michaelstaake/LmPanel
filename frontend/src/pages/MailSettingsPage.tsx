import { useEffect, useRef, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import SettingsLayout from "./SettingsLayout";

export default function MailSettingsPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const prevValues = useRef({
    mail_email_address: "",
    mail_email_username: "",
    mail_email_server: "",
    mail_email_port: 587,
    mail_email_security: "starttls",
    mail_email_from_name: "",
  });

  const [emailAddress, setEmailAddress] = useState("");
  const [emailUsername, setEmailUsername] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [emailServer, setEmailServer] = useState("");
  const [emailPort, setEmailPort] = useState("587");
  const [emailSecurity, setEmailSecurity] = useState("starttls");
  const [emailFromName, setEmailFromName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState<string | null>(null);
  const [hasPassword, setHasPassword] = useState(false);

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
      const address = response.mail_email_address ?? "";
      const username = response.mail_email_username ?? "";
      const server = response.mail_email_server ?? "";
      const port = response.mail_email_port ?? 587;
      const security = response.mail_email_security ?? "starttls";
      const fromName = response.mail_email_from_name ?? "";

      prevValues.current = { mail_email_address: address, mail_email_username: username, mail_email_server: server, mail_email_port: port, mail_email_security: security, mail_email_from_name: fromName };

      setEmailAddress(address);
      setEmailUsername(username);
      setEmailServer(server);
      setEmailPort(String(port));
      setEmailSecurity(security);
      setEmailFromName(fromName);
      setHasPassword(response.mail_email_password_set ?? false);
      if (response.mail_email_password_set) {
        setEmailPassword("\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022");
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load mail settings");
    } finally {
      setIsLoading(false);
    }
  }

  async function updateField(field: string, value: string | number) {
    if (!token) return;

    const prev = { ...prevValues.current };
    prevValues.current = { ...prev, [field]: value };

    const fieldMap: Record<string, (v: string | number) => void> = {
      mail_email_address: (v) => setEmailAddress(v as string),
      mail_email_username: (v) => setEmailUsername(v as string),
      mail_email_server: (v) => setEmailServer(v as string),
      mail_email_port: (v) => setEmailPort(String(v)),
      mail_email_security: (v) => setEmailSecurity(v as string),
      mail_email_from_name: (v) => setEmailFromName(v as string),
    };

    fieldMap[field]?.(value);
    setIsSaving(field);

    try {
      await apiPatch("/api/admin/settings", { [field]: value }, token);
      showSuccess("Mail settings updated.");
    } catch (error) {
      prevValues.current = prev;
      setEmailAddress(prev.mail_email_address);
      setEmailUsername(prev.mail_email_username);
      setEmailServer(prev.mail_email_server);
      setEmailPort(String(prev.mail_email_port));
      setEmailSecurity(prev.mail_email_security);
      setEmailFromName(prev.mail_email_from_name);
      showError(error instanceof Error ? error.message : "Failed to update mail setting");
    } finally {
      setIsSaving(null);
    }
  }

  async function commitEmailPassword() {
    if (!token) return;
    if (emailPassword === "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" || emailPassword === "") {
      if (hasPassword) {
        await clearEmailPassword();
      }
      return;
    }

    setIsSaving("mail_email_password");
    try {
      await apiPatch("/api/admin/settings", { mail_email_password: emailPassword }, token);
      setHasPassword(true);
      setEmailPassword("\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022");
      showSuccess("Email password updated.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to update email password");
    } finally {
      setIsSaving(null);
    }
  }

  async function clearEmailPassword() {
    if (!token) return;

    setIsSaving("mail_email_password");
    try {
      await apiPatch("/api/admin/settings", { mail_email_password: "" }, token);
      setHasPassword(false);
      setEmailPassword("");
      showSuccess("Email password removed.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to clear email password");
    } finally {
      setIsSaving(null);
    }
  }

  return (
    <SettingsLayout title="Mail">
      <section className="grid gap-4">
        <article>
          <h2 className="font-display text-xl">Mail</h2>
          <p className="mt-1 text-sm text-sand/65">
            Configure the email server settings used for sending notifications.
          </p>

          <div className="mt-5 grid gap-3">
            <div className="surface-muted py-4 px-4">
              <div className="grid gap-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Email Address</span>
                  <p className="text-sm text-sand/65">
                    The notification email address where alerts will be sent.
                  </p>
                  <input
                    type="email"
                    className="field w-full max-w-md px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailAddress}
                    onChange={(e) => setEmailAddress(e.target.value)}
                    onBlur={() => {
                      if (emailAddress.trim() !== prevValues.current.mail_email_address) {
                        void updateField("mail_email_address", emailAddress.trim());
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void updateField("mail_email_address", emailAddress.trim());
                      }
                    }}
                    disabled={isLoading || isSaving === "mail_email_address"}
                    placeholder="admin@example.com"
                  />
                </label>
              </div>
            </div>

            <div className="surface-muted py-4 px-4">
              <div className="grid gap-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Email Username</span>
                  <p className="text-sm text-sand/65">
                    The username for authenticating with the email server.
                  </p>
                  <input
                    type="text"
                    className="field w-full max-w-md px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailUsername}
                    onChange={(e) => setEmailUsername(e.target.value)}
                    onBlur={() => {
                      if (emailUsername.trim() !== prevValues.current.mail_email_username) {
                        void updateField("mail_email_username", emailUsername.trim());
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void updateField("mail_email_username", emailUsername.trim());
                      }
                    }}
                    disabled={isLoading || isSaving === "mail_email_username"}
                    placeholder="admin@example.com"
                  />
                </label>
              </div>
            </div>

            <div className="surface-muted py-4 px-4">
              <div className="grid gap-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Email Password</span>
                  <p className="text-sm text-sand/65">
                    {hasPassword
                      ? "A password is saved. Enter a new value to replace it, or clear it below."
                      : "The password for authenticating with the email server."}
                  </p>
                  <input
                    type="password"
                    className="field w-full max-w-md px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailPassword}
                    onChange={(e) => setEmailPassword(e.target.value)}
                    onBlur={() => void commitEmailPassword()}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void commitEmailPassword();
                      }
                    }}
                    disabled={isLoading || isSaving === "mail_email_password"}
                    autoComplete="off"
                    placeholder={hasPassword ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" : "Email password"}
                  />
                  {hasPassword ? (
                    <button
                      type="button"
                      className="btn-secondary px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                      onClick={() => void clearEmailPassword()}
                      disabled={isLoading || isSaving === "mail_email_password"}
                    >
                      Clear password
                    </button>
                  ) : null}
                </label>
              </div>
            </div>

            <div className="surface-muted py-4 px-4">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Email Server</span>
                  <p className="text-sm text-sand/65">
                    The SMTP server hostname.
                  </p>
                  <input
                    type="text"
                    className="field w-full max-w-md px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailServer}
                    onChange={(e) => setEmailServer(e.target.value)}
                    onBlur={() => {
                      if (emailServer.trim() !== prevValues.current.mail_email_server) {
                        void updateField("mail_email_server", emailServer.trim());
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void updateField("mail_email_server", emailServer.trim());
                      }
                    }}
                    disabled={isLoading || isSaving === "mail_email_server"}
                    placeholder="smtp.example.com"
                  />
                </label>

                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Email Port</span>
                  <p className="text-sm text-sand/65">
                    The SMTP server port number.
                  </p>
                  <select
                    className="field w-full max-w-xs px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailPort}
                    onChange={(e) => void updateField("mail_email_port", Number(e.target.value))}
                    disabled={isLoading || isSaving === "mail_email_port"}
                  >
                    <option value="25">25 (SMTP)</option>
                    <option value="465">465 (SMTPS)</option>
                    <option value="587">587 (SMTP/TLS)</option>
                    <option value="2525">2525 (Alternative)</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="surface-muted py-4 px-4">
              <div className="grid gap-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">Email Security</span>
                  <p className="text-sm text-sand/65">
                    The security protocol used to connect to the email server.
                  </p>
                  <select
                    className="field w-full max-w-xs px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailSecurity}
                    onChange={(e) => void updateField("mail_email_security", e.target.value)}
                    disabled={isLoading || isSaving === "mail_email_security"}
                  >
                    <option value="starttls">STARTTLS</option>
                    <option value="tls">TLS</option>
                    <option value="none">None</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="surface-muted py-4 px-4">
              <div className="grid gap-2">
                <label className="grid gap-2">
                  <span className="text-sm font-semibold text-sand">From Name</span>
                  <p className="text-sm text-sand/65">
                    The display name shown in the "From" field of notification emails.
                  </p>
                  <input
                    type="text"
                    className="field w-full max-w-md px-3 py-2 text-sm text-sand focus:outline-none focus:ring-2 focus:ring-sand/20"
                    value={emailFromName}
                    onChange={(e) => setEmailFromName(e.target.value)}
                    onBlur={() => {
                      if (emailFromName.trim() !== prevValues.current.mail_email_from_name) {
                        void updateField("mail_email_from_name", emailFromName.trim());
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void updateField("mail_email_from_name", emailFromName.trim());
                      }
                    }}
                    disabled={isLoading || isSaving === "mail_email_from_name"}
                    placeholder="LmPanel Notifications"
                  />
                </label>
              </div>
            </div>
          </div>
        </article>
      </section>
    </SettingsLayout>
  );
}
