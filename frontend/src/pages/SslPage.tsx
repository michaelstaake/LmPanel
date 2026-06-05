import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  fetchSslStatus,
  obtainLetsEncryptCertificate,
  pollUntilTaskComplete,
  renewLetsEncryptCertificate,
  updateSslSettings,
} from "../lib/api";
import type { SslStatusRecord, SslTaskResponse } from "../lib/records";

export default function SslPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [status, setStatus] = useState<SslStatusRecord | null>(null);
  const [localEmail, setLocalEmail] = useState("");
  const [cloudflareToken, setCloudflareToken] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isIssuing, setIsIssuing] = useState(false);
  const hasLoaded = useRef(false);

  useEffect(() => {
    if (!token || hasLoaded.current) {
      return;
    }
    hasLoaded.current = true;
    void loadStatus(token);
  }, [token]);

  async function loadStatus(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await fetchSslStatus<SslStatusRecord>(activeToken);
      setStatus(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load SSL settings");
    } finally {
      setIsLoading(false);
    }
  }

  async function saveSettings() {
    if (!token) {
      return;
    }

    setIsSavingSettings(true);
    try {
      const payload: { letsencrypt_email?: string; cloudflare_api_token?: string } = {
        letsencrypt_email: localEmail.trim(),
      };
      if (cloudflareToken !== "") {
        payload.cloudflare_api_token = cloudflareToken;
      }

      const response = await updateSslSettings<typeof payload, SslStatusRecord>(payload, token);
      setStatus(response);
      setCloudflareToken("");
      showSuccess("SSL settings saved.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save SSL settings");
    } finally {
      setIsSavingSettings(false);
    }
  }

  async function clearCloudflareToken() {
    if (!token) {
      return;
    }

    setIsSavingSettings(true);
    try {
      const response = await updateSslSettings<{ cloudflare_api_token: string }, SslStatusRecord>(
        { cloudflare_api_token: "" },
        token,
      );
      setStatus(response);
      setCloudflareToken("");
      showSuccess("Cloudflare API token removed.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to clear Cloudflare token");
    } finally {
      setIsSavingSettings(false);
    }
  }

  async function runCertificateAction(action: "issue" | "renew") {
    if (!token || !status) {
      return;
    }

    setIsIssuing(true);
    try {
      const startResponse =
        action === "issue"
          ? await obtainLetsEncryptCertificate<SslTaskResponse>(token)
          : await renewLetsEncryptCertificate<SslTaskResponse>(token);

      const task = await pollUntilTaskComplete(startResponse.task_id, token, 600, 2000);
      if (task.status === "error") {
        throw new Error(task.error || "Certificate operation failed");
      }
      if (task.status === "cancelled") {
        throw new Error("Certificate operation was cancelled");
      }

      await loadStatus(token);
      showSuccess(action === "issue" ? "Let's Encrypt certificate obtained." : "Certificate renewed.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Certificate operation failed");
      if (token) {
        await loadStatus(token);
      }
    } finally {
      setIsIssuing(false);
    }
  }

  const canOperate = Boolean(status?.letsencrypt_available) && !isLoading && !isIssuing;
  const certificate = status?.certificate;

  return (
    <section className="grid gap-4">
      <article className="rounded-2xl border border-black/10 bg-white/80 p-5 shadow-sm backdrop-blur">
        <h2 className="font-display text-xl">SSL</h2>
        <p className="mt-2 text-sm text-black/65">
          Obtain a trusted certificate from Let&apos;s Encrypt using Cloudflare DNS validation. Your homelab can keep custom HTTPS ports; validation does not require port 80 on LmPanel.
        </p>

        <div className="mt-4 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4 text-sm text-black/70">
          <p className="font-semibold text-black">Prerequisites</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              Set the public <strong>URL</strong> on the{" "}
              <Link to="/settings" className="font-semibold text-ink underline underline-offset-2">
                Configuration
              </Link>{" "}
              tab.
            </li>
            <li>Hostname DNS must be managed in Cloudflare.</li>
            <li>Cloudflare API token with Zone → DNS → Edit for that zone.</li>
            <li>Reverse proxy may use any external HTTPS port; the URL setting has no port.</li>
          </ul>
        </div>

        <div className="mt-5 grid gap-3">
          <div className="rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <div className="text-sm font-semibold text-black">Certificate status</div>
            {isLoading ? (
              <p className="mt-2 text-sm text-black/65">Loading...</p>
            ) : certificate ? (
              <dl className="mt-3 grid gap-2 text-sm text-black/70">
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="font-semibold text-black">Subject</dt>
                  <dd>{certificate.subject ?? "—"}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="font-semibold text-black">Issuer</dt>
                  <dd className="max-w-md text-right">{certificate.issuer}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="font-semibold text-black">Expires</dt>
                  <dd>
                    {new Date(certificate.not_after).toLocaleString()} ({certificate.days_remaining} days left)
                  </dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="font-semibold text-black">Type</dt>
                  <dd>
                    {certificate.is_lets_encrypt
                      ? "Let's Encrypt"
                      : certificate.is_self_signed
                        ? "Self-signed"
                        : "Custom"}
                  </dd>
                </div>
                {status?.public_url ? (
                  <div className="flex flex-wrap justify-between gap-2">
                    <dt className="font-semibold text-black">Matches configured URL</dt>
                    <dd>{certificate.domain_matches ? "Yes" : "No"}</dd>
                  </div>
                ) : null}
              </dl>
            ) : (
              <p className="mt-2 text-sm text-black/65">No certificate files found yet.</p>
            )}
            {status?.public_url ? (
              <p className="mt-3 text-sm text-black/65">
                Configured URL: <span className="font-semibold text-black">{status.public_url}</span>
              </p>
            ) : (
              <p className="mt-3 text-sm text-amber-900/80">Configure a public URL on the Configuration tab to enable Let&apos;s Encrypt.</p>
            )}
          </div>

          <div className="grid gap-3 rounded-2xl border border-black/10 bg-[#fffdf7] px-4 py-4">
            <label className="grid gap-2">
              <span className="text-sm font-semibold text-black">Let&apos;s Encrypt account email</span>
              <input
                type="email"
                className="max-w-md rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                value={localEmail}
                onChange={(e) => setLocalEmail(e.target.value)}
                disabled={isLoading || isSavingSettings}
                placeholder="admin@example.com"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-sm font-semibold text-black">Cloudflare API token</span>
              <p className="text-sm text-black/65">
                {status?.cloudflare_api_token_set
                  ? "A token is saved. Enter a new value to replace it, or clear it below."
                  : "Create a token with DNS Edit permission for your zone."}
              </p>
              <input
                type="password"
                className="max-w-md rounded-xl border border-black/15 bg-white px-3 py-2 text-sm text-black focus:outline-none focus:ring-2 focus:ring-ink/20"
                value={cloudflareToken}
                onChange={(e) => setCloudflareToken(e.target.value)}
                disabled={isLoading || isSavingSettings}
                placeholder={status?.cloudflare_api_token_set ? "••••••••" : "Cloudflare API token"}
                autoComplete="off"
              />
            </label>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => void saveSettings()}
                disabled={isLoading || isSavingSettings}
              >
                {isSavingSettings ? "Saving..." : "Save SSL settings"}
              </button>
              {status?.cloudflare_api_token_set ? (
                <button
                  type="button"
                  className="rounded-xl border border-black/10 bg-white px-4 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => void clearCloudflareToken()}
                  disabled={isLoading || isSavingSettings}
                >
                  Clear Cloudflare token
                </button>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => void runCertificateAction("issue")}
              disabled={!canOperate}
              title={!status?.letsencrypt_available ? "Configure URL, email, and Cloudflare token first" : undefined}
            >
              {isIssuing ? "Working..." : "Obtain certificate"}
            </button>
            <button
              type="button"
              className="rounded-xl border border-black/10 bg-white px-4 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => void runCertificateAction("renew")}
              disabled={!canOperate}
              title={!status?.letsencrypt_available ? "Configure URL, email, and Cloudflare token first" : undefined}
            >
              Renew certificate
            </button>
          </div>
        </div>
      </article>
    </section>
  );
}
