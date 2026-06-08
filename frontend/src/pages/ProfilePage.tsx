import { FormEvent, useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import { AccountToolUsageStatusRecord, AccountUsageStatusRecord, StatusResponse } from "../lib/records";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import Modal from "../components/ui/Modal";

export default function ProfilePage() {
  const { token, logout, updateProfile, user } = useAuth();
  const { showError, showSuccess } = useToast();
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSavingEmail, setIsSavingEmail] = useState(false);
  const [isSavingPassword, setIsSavingPassword] = useState(false);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const [accountUsage, setAccountUsage] = useState<AccountUsageStatusRecord | null>(null);
  const [accountToolUsage, setAccountToolUsage] = useState<AccountToolUsageStatusRecord | null>(null);
  const [packageName, setPackageName] = useState<string | null>(null);

  useEffect(() => {
    setEmail(user?.email ?? "");
  }, [user?.email]);

  useEffect(() => {
    if (!token) {
      return;
    }
    apiGet<StatusResponse>("/api/status", token).then((response) => {
      setAccountUsage(response.account_usage ?? null);
      setAccountToolUsage(response.account_tool_usage ?? null);
      setPackageName(response.package_name ?? null);
    }).catch(() => {});
  }, [token]);

  async function handleEmailSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedEmail = email.trim();

    if (!trimmedEmail) {
      showError("Email is required.");
      return;
    }

    if (trimmedEmail === (user?.email ?? "")) {
      showError("No email changes to save.");
      return;
    }

    setIsSavingEmail(true);
    try {
      await updateProfile({ email: trimmedEmail });
      showSuccess("Email updated.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Unable to update email.");
    } finally {
      setIsSavingEmail(false);
    }
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextPassword = password.trim();
    const nextConfirmPassword = confirmPassword.trim();

    if (!nextPassword) {
      showError("New password is required.");
      return;
    }

    if (nextPassword.length < 8) {
      showError("Password must be at least 8 characters.");
      return;
    }

    if (nextPassword !== nextConfirmPassword) {
      showError("Password confirmation does not match.");
      return;
    }

    setIsSavingPassword(true);
    try {
      await updateProfile({ password: nextPassword });
      setPassword("");
      setConfirmPassword("");
      showSuccess("Password updated.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Unable to update password.");
    } finally {
      setIsSavingPassword(false);
    }
  }

  const roleLabel = user?.is_admin ? "Admin" : "Standard";
  const packageLabel = packageName ? ` • ${packageName}` : "";
  const showAccountUsage = accountUsage?.enabled;
  const showAccountToolUsage = accountToolUsage?.enabled;
  const numberFormatter = new Intl.NumberFormat();
  const adminUsage = Boolean(user?.is_admin || accountUsage?.is_admin || accountToolUsage?.is_admin);
  const atAnyLimit = !adminUsage && Boolean(accountUsage?.at_limit || accountToolUsage?.at_limit);

  function isUnlimitedPeriod(limitTokens: number) {
    return limitTokens === 0 || adminUsage;
  }

  function clampPercent(value: number | null | undefined) {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return 0;
    }
    return Math.max(0, Math.min(100, value));
  }

  function formatWholePercent(value: number) {
    return `${Math.round(clampPercent(value))}%`;
  }

  function formatResetIn(seconds: number | null) {
    if (seconds === null || seconds < 0) return null;
    const days = Math.floor(seconds / (60 * 60 * 24));
    if (days > 0) {
      const remainingHours = Math.floor((seconds % (60 * 60 * 24)) / (60 * 60));
      if (remainingHours > 0) {
        return `${days} day${days !== 1 ? "s" : ""}, ${remainingHours} hour${remainingHours !== 1 ? "s" : ""}`;
      }
      return `${days} day${days !== 1 ? "s" : ""}`;
    }
    const hours = Math.floor(seconds / (60 * 60));
    if (hours > 0) {
      const remainingMinutes = Math.floor((seconds % (60 * 60)) / 60);
      if (remainingMinutes > 0) {
        return `${hours} hour${hours !== 1 ? "s" : ""}, ${remainingMinutes} minute${remainingMinutes !== 1 ? "s" : ""}`;
      }
      return `${hours} hour${hours !== 1 ? "s" : ""}`;
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes > 0) {
      return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
    }
    return null;
  }

  return (
    <section className="grid gap-4">
      <article className=" border border-white/10 bg-white/85 p-5 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sand/45">{roleLabel}</p>
            <h2 className="mt-2 font-display text-2xl text-sand">Profile</h2>
            <p className="mt-2 text-sm text-sand/60">
              Signed in as <span className="font-semibold text-sand">{user?.username ?? "Unknown user"}</span>
            </p>
          </div>
          <div className="flex shrink-0 items-start gap-2">
            <button
              type="button"
              onClick={() => setEmailModalOpen(true)}
              className="shrink-0  border border-white/15 bg-white/10 px-4 py-3 text-sand text-sm font-semibold text-sand transition hover:bg-white/10"
            >
              Update email
            </button>
            <button
              type="button"
              onClick={() => setPasswordModalOpen(true)}
              className="shrink-0  border border-white/15 bg-white/10 px-4 py-3 text-sand text-sm font-semibold text-sand transition hover:bg-white/10"
            >
              Update password
            </button>
            <button
              type="button"
              onClick={logout}
              className="shrink-0  border border-white/15 bg-white/10 px-4 py-3 text-sand text-sm font-semibold text-sand transition hover:bg-white/10"
            >
              Log out
            </button>
          </div>
        </div>
      </article>

      {(showAccountUsage || showAccountToolUsage) && (
        <article className=" border border-white/10 bg-white/85 p-5 shadow-sm backdrop-blur">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sand/45">Your Usage{packageLabel}</p>
          <p className="mt-1 text-sm text-sand/60">
            {adminUsage
              ? "Token and web search usage."
              : atAnyLimit
                ? accountToolUsage?.at_limit && !accountUsage?.at_limit
                  ? "You have reached a web search usage limit. Web search is unavailable until your usage resets."
                  : accountUsage?.at_limit && accountToolUsage?.at_limit
                    ? "You have reached token and web search usage limits. Chat, API, and web search are unavailable until your usage resets."
                    : "You have reached a usage limit. Chat and API access are unavailable until your usage resets."
                : "Token and web search usage against your account limits."}
          </p>

          {showAccountUsage && (
            <>
              <p className="mt-4 text-xs font-semibold uppercase tracking-[0.18em] text-sand/45">Token Usage</p>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {accountUsage.periods.map((period) => (
                  <div key={period.id} className=" p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sand/45">{period.label}</p>
                    {isUnlimitedPeriod(period.limit_tokens) ? (
                      <>
                        <p className="mt-2 font-display text-3xl text-sand">{numberFormatter.format(period.used_tokens)}</p>
                        <p className="mt-1 text-sm text-sand/55">Tokens</p>
                        {(() => { const reset = formatResetIn(period.resets_in_seconds); return reset ? <p className="mt-1 text-xs text-sand/40">Resets in {reset}</p> : null; })()}
                      </>
                    ) : (
                      <>
                        <p className="mt-2 font-display text-3xl text-sand">{formatWholePercent(period.percent)}</p>
                        <p className="mt-1 text-sm text-sand/55">
                          {numberFormatter.format(period.used_tokens)} / {numberFormatter.format(period.limit_tokens)} tokens
                        </p>
                        {(() => { const reset = formatResetIn(period.resets_in_seconds); return reset ? <p className="mt-1 text-xs text-sand/40">Resets in {reset}</p> : null; })()}
                        <div className="mt-3 h-2 overflow-hidden  bg-black/10">
                          <div
                            className={`h-full  ${period.percent >= 100 ? "bg-[#c63f3f]" : period.percent >= 80 ? "bg-[#c98a13]" : "bg-[#2f8f4e]"}`}
                            style={{ width: `${clampPercent(period.percent)}%` }}
                          />
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {showAccountToolUsage && (
            <>
              <p className={`text-xs font-semibold uppercase tracking-[0.18em] text-sand/45 ${showAccountUsage ? "mt-6" : "mt-4"}`}>Web Search Usage</p>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {accountToolUsage.periods.map((period) => (
                  <div key={period.id} className=" p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sand/45">{period.label}</p>
                    {isUnlimitedPeriod(period.limit_tokens) ? (
                      <>
                        <p className="mt-2 font-display text-3xl text-sand">{numberFormatter.format(period.used_tokens)}</p>
                        <p className="mt-1 text-sm text-sand/55">Searches</p>
                        {(() => { const reset = formatResetIn(period.resets_in_seconds); return reset ? <p className="mt-1 text-xs text-sand/40">Resets in {reset}</p> : null; })()}
                      </>
                    ) : (
                      <>
                        <p className="mt-2 font-display text-3xl text-sand">{formatWholePercent(period.percent)}</p>
                        <p className="mt-1 text-sm text-sand/55">
                          {numberFormatter.format(period.used_tokens)} / {numberFormatter.format(period.limit_tokens)} searches
                        </p>
                        {(() => { const reset = formatResetIn(period.resets_in_seconds); return reset ? <p className="mt-1 text-xs text-sand/40">Resets in {reset}</p> : null; })()}
                        <div className="mt-3 h-2 overflow-hidden  bg-black/10">
                          <div
                            className={`h-full  ${period.percent >= 100 ? "bg-[#c63f3f]" : period.percent >= 80 ? "bg-[#c98a13]" : "bg-[#2f8f4e]"}`}
                            style={{ width: `${clampPercent(period.percent)}%` }}
                          />
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </article>
      )}

      <Modal open={emailModalOpen} onClose={() => setEmailModalOpen(false)} labelledBy="update-email-title" panelClassName="max-w-md">
        <div className="p-5">
          <div className="flex items-start justify-between">
            <h2 id="update-email-title" className="font-display text-xl">Update email</h2>
            <button
              type="button"
              onClick={() => setEmailModalOpen(false)}
              className="shrink-0  p-1 text-sand/45 transition hover:bg-white/10 hover:text-sand"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <form className="mt-5 space-y-4" onSubmit={handleEmailSubmit}>
            <label className="block text-sm text-sand/70">
              <span className="mb-2 block font-semibold text-sand">Email</span>
              <input
                className="w-full  border border-white/10 bg-white px-4 py-3 outline-none transition focus:border-white/25"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
              />
            </label>
            <button
              className=" bg-sand px-4 py-3 font-semibold text-canvas transition hover:bg-sand/80 disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={isSavingEmail}
            >
              {isSavingEmail ? "Saving..." : "Update email"}
            </button>
          </form>
        </div>
      </Modal>

      <Modal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} labelledBy="update-password-title" panelClassName="max-w-md">
        <div className="p-5">
          <div className="flex items-start justify-between">
            <h2 id="update-password-title" className="font-display text-xl">Update password</h2>
            <button
              type="button"
              onClick={() => setPasswordModalOpen(false)}
              className="shrink-0  p-1 text-sand/45 transition hover:bg-white/10 hover:text-sand"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <form className="mt-5 space-y-4" onSubmit={handlePasswordSubmit}>
            <label className="block text-sm text-sand/70">
              <span className="mb-2 block font-semibold text-sand">New password</span>
              <input
                className="w-full  border border-white/10 bg-white px-4 py-3 outline-none transition focus:border-white/25"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="new-password"
                placeholder="Enter a new password"
              />
            </label>
            <label className="block text-sm text-sand/70">
              <span className="mb-2 block font-semibold text-sand">Confirm new password</span>
              <input
                className="w-full  border border-white/10 bg-white px-4 py-3 outline-none transition focus:border-white/25"
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                placeholder="Repeat the new password"
              />
            </label>
            <button
              className=" bg-sand px-4 py-3 font-semibold text-canvas transition hover:bg-sand/80 disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={isSavingPassword}
            >
              {isSavingPassword ? "Saving..." : "Update password"}
            </button>
          </form>
        </div>
      </Modal>
    </section>
  );
}