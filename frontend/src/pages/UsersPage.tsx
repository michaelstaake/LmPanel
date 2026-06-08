import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Modal from "../components/ui/Modal";
import { apiGet, apiPatch, apiPost, deleteUser, toggleUserActive, updateUserEmail, updateUserPassword, fetchPackages } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { PackageRecord, UserRecord, UserTokenUsageRecord, UserUpdateResponse } from "../lib/records";
import { isValidUsername, sanitizeUsernameInput, USERNAME_VALIDATION_MESSAGE } from "../lib/username";
import SettingsLayout from "./SettingsLayout";

type CreateUserPayload = {
  username: string;
  email: string;
  password: string;
  is_admin: boolean;
  is_active: boolean;
  package_id?: number | null;
};

export default function UsersPage() {
  const { token, user: currentUser } = useAuth();
  const { showError, showSuccess } = useToast();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [userTokenUsages, setUserTokenUsages] = useState<Record<number, UserTokenUsageRecord>>({});
  const [packages, setPackages] = useState<PackageRecord[]>([]);
  const [newUser, setNewUser] = useState<CreateUserPayload>({ username: "", email: "", password: "", is_admin: false, is_active: true, package_id: 2 });
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreatingUser, setIsCreatingUser] = useState(false);
  const [isGeneratingPassword, setIsGeneratingPassword] = useState(false);
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  // View usage modal
  const [isUsageModalOpen, setIsUsageModalOpen] = useState(false);
  const [selectedUsageUser, setSelectedUsageUser] = useState<UserRecord | null>(null);
  const [isLoadingUsage, setIsLoadingUsage] = useState(false);

  // Update email modal
  const [isEmailModalOpen, setIsEmailModalOpen] = useState(false);
  const [selectedEmailUser, setSelectedEmailUser] = useState<UserRecord | null>(null);
  const [emailValue, setEmailValue] = useState("");
  const [isSavingEmail, setIsSavingEmail] = useState(false);

  // Update password modal
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false);
  const [selectedPasswordUser, setSelectedPasswordUser] = useState<UserRecord | null>(null);
  const [passwordValue, setPasswordValue] = useState("");
  const [confirmPasswordValue, setConfirmPasswordValue] = useState("");
  const [isSavingPassword, setIsSavingPassword] = useState(false);

  // Delete confirmation modal
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedDeleteUser, setSelectedDeleteUser] = useState<UserRecord | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (!token) {
      return;
    }
    void refreshUsers(token);
    void refreshTokenUsage(token);
    void loadPackages(token);
  }, [token]);

  async function refreshUsers(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<UserRecord[]>("/api/admin/users", activeToken);
      setUsers(response.map((user) => ({ ...user, password: "" })));
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load users");
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshTokenUsage(activeToken: string) {
    try {
      const response = await apiGet<UserTokenUsageRecord[]>("/api/admin/users/token-usage", activeToken);
      const usageMap: Record<number, UserTokenUsageRecord> = {};
      for (const usage of response) {
        usageMap[usage.user_id] = usage;
      }
      setUserTokenUsages(usageMap);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load token usage");
    }
  }

  async function loadPackages(activeToken: string) {
    try {
      const response = await apiGet<PackageRecord[]>("/api/admin/packages", activeToken);
      setPackages(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load packages");
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    if (!isValidUsername(newUser.username)) {
      showError(USERNAME_VALIDATION_MESSAGE);
      return;
    }

    setIsCreatingUser(true);

    try {
      const payload: CreateUserPayload = {
        username: newUser.username,
        email: newUser.email,
        password: newUser.password,
        is_admin: newUser.is_admin,
        is_active: newUser.is_active,
      };
      if (!newUser.is_admin) {
        payload.package_id = newUser.package_id;
      }
      const response = await apiPost<CreateUserPayload, UserUpdateResponse>("/api/admin/users", payload, token);
      setUsers((current) => [...current, { ...response.user, password: "" }].sort((left, right) => left.username.localeCompare(right.username)));
      setNewUser({ username: "", email: "", password: "", is_admin: false, is_active: true, package_id: 2 });
      setIsCreateModalOpen(false);
      showSuccess(`Created user ${response.user.username}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "User creation failed");
    } finally {
      setIsCreatingUser(false);
    }
  }

  function formatTokens(tokens: number): string {
    if (tokens >= 1_000_000_000) {
      return `${(tokens / 1_000_000_000).toFixed(1)}B`;
    }
    if (tokens >= 1_000_000) {
      return `${(tokens / 1_000_000).toFixed(1)}M`;
    }
    if (tokens >= 1_000) {
      return `${(tokens / 1_000).toFixed(1)}K`;
    }
    return tokens.toString();
  }

  function generateRandomPassword(length = 16) {
    const upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const lower = "abcdefghijklmnopqrstuvwxyz";
    const digits = "0123456789";
    const special = "!@#$%^&*";
    const all = upper + lower + digits + special;
    let password = "";
    for (let i = 0; i < length; i++) {
      password += all[Math.floor(Math.random() * all.length)];
    }
    return password;
  }

  async function handleGeneratePassword() {
    setIsGeneratingPassword(true);
    setNewUser((current) => ({ ...current, password: generateRandomPassword() }));
    setIsGeneratingPassword(false);
  }

  // View usage
  async function handleViewUsage(user: UserRecord) {
    setSelectedUsageUser(user);
    setIsUsageModalOpen(true);
    setIsLoadingUsage(true);
    try {
      const response = await apiGet<UserTokenUsageRecord[]>(`/api/admin/users/${user.id}/token-usage`, token);
      if (response.length > 0) {
        setUserTokenUsages((current) => ({ ...current, [user.id]: response[0] }));
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load token usage");
    } finally {
      setIsLoadingUsage(false);
    }
  }

  // Update email
  function openUpdateEmailModal(user: UserRecord) {
    setSelectedEmailUser(user);
    setEmailValue(user.email);
    setIsEmailModalOpen(true);
  }

  async function handleUpdateEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedEmailUser) {
      return;
    }

    const trimmedEmail = emailValue.trim();
    if (!trimmedEmail) {
      showError("Email is required.");
      return;
    }

    if (trimmedEmail === selectedEmailUser.email) {
      showError("No email changes to save.");
      return;
    }

    setIsSavingEmail(true);
    try {
      const response = await updateUserEmail(selectedEmailUser.id, trimmedEmail, token);
      setUsers((current) => current.map((item) => (item.id === selectedEmailUser.id ? { ...response.user, password: "" } : item)));
      setIsEmailModalOpen(false);
      showSuccess(`Email updated for ${response.user.username}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Unable to update email.");
    } finally {
      setIsSavingEmail(false);
    }
  }

  // Update password
  function openUpdatePasswordModal(user: UserRecord) {
    setSelectedPasswordUser(user);
    setPasswordValue("");
    setConfirmPasswordValue("");
    setIsPasswordModalOpen(true);
  }

  async function handleUpdatePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedPasswordUser) {
      return;
    }

    const nextPassword = passwordValue.trim();
    const nextConfirmPassword = confirmPasswordValue.trim();

    if (!nextPassword) {
      showError("Password is required.");
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
      const response = await updateUserPassword(selectedPasswordUser.id, nextPassword, token);
      setIsPasswordModalOpen(false);
      showSuccess(`Password updated for ${response.user.username}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Unable to update password.");
    } finally {
      setIsSavingPassword(false);
    }
  }

  // Toggle active
  async function handleToggleActive(user: UserRecord) {
    if (!token) {
      return;
    }

    try {
      const response = await toggleUserActive(user.id, token);
      setUsers((current) => current.map((item) => (item.id === user.id ? { ...response.user, password: "" } : item)));
      showSuccess(`${response.user.is_active ? "Enabled" : "Disabled"} ${response.user.username}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Unable to toggle user status.");
    }
  }

  // Delete user
  function openDeleteModal(user: UserRecord) {
    setSelectedDeleteUser(user);
    setIsDeleteModalOpen(true);
  }

  async function handleDeleteUser() {
    if (!token || !selectedDeleteUser) {
      return;
    }

    setIsDeleting(true);
    try {
      await deleteUser(selectedDeleteUser.id, token);
      setUsers((current) => current.filter((user) => user.id !== selectedDeleteUser.id));
      setIsDeleteModalOpen(false);
      showSuccess(`Deleted user ${selectedDeleteUser.username}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Unable to delete user.");
    } finally {
      setIsDeleting(false);
    }
  }

  const visibleUsers = currentUser ? users.filter((user) => user.id !== currentUser.id) : users;

  return (
    <SettingsLayout title="Users">
      <section className="grid gap-4">
      <article>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl">Users</h2>
          </div>
          <button className=" btn-secondary px-4 py-3 text-sm font-semibold" type="button" onClick={() => setIsCreateModalOpen(true)}>
            Add user
          </button>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visibleUsers.map((user) => (
            <div key={user.id} className="surface-muted p-4">
              <div className="flex items-center justify-between">
                <h3 className="font-display text-lg text-sand">{user.username}</h3>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {user.is_admin ? <span className="badge-warning px-2.5 py-1 text-xs font-semibold">Admin</span> : null}
                {user.package_name ? <span className="badge-info px-2.5 py-1 text-xs font-semibold">{user.package_name}</span> : null}
                {user.is_active ? <span className="badge-success px-2.5 py-1 text-xs font-semibold">Enabled</span> : <span className="bg-white/10 px-2.5 py-1 text-xs font-semibold text-sand/60">Disabled</span>}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button className="btn-secondary px-2.5 py-1.5 text-xs font-semibold text-sand transition hover:bg-white/10" type="button" onClick={() => handleViewUsage(user)}>
                  View usage
                </button>
                <button className="btn-secondary px-2.5 py-1.5 text-xs font-semibold text-sand transition hover:bg-white/10" type="button" onClick={() => openUpdateEmailModal(user)}>
                  Update email
                </button>
                <button className="btn-secondary px-2.5 py-1.5 text-xs font-semibold text-sand transition hover:bg-white/10" type="button" onClick={() => openUpdatePasswordModal(user)}>
                  Update password
                </button>
                <button className={` border px-2.5 py-1.5 text-xs font-semibold transition hover:bg-white/10 ${user.is_active ? "btn-secondary text-sand" : "badge-success"}`} type="button" onClick={() => handleToggleActive(user)}>
                  {user.is_active ? "Disable" : "Enable"}
                </button>
                <button className="btn-danger px-2.5 py-1.5 text-xs font-semibold" type="button" onClick={() => openDeleteModal(user)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
          {isLoading ? <p className="surface-muted px-4 py-6 text-sm text-sand/60">Loading users...</p> : null}
          {!isLoading && visibleUsers.length === 0 ? (
            currentUser?.is_admin ? (
              <div className=" border border-dashed border-white/15 bg-white/5 px-5 py-6 text-sm text-sand/65">
                <p className="font-semibold text-sand">There are no other users yet.</p>
                <p className="mt-2">
                  If you want to update your own account, go to the <Link to="/profile" className="font-semibold text-sand underline decoration-black/30 underline-offset-4">Profile page</Link>.
                </p>
              </div>
            ) : (
              <p className=" border border-dashed border-white/15 px-4 py-6 text-sm text-sand/60">No users created yet.</p>
            )
          ) : null}
        </div>
      </article>

      {/* Create user modal */}
      <Modal open={isCreateModalOpen} onClose={() => setIsCreateModalOpen(false)} labelledBy="user-create-title" panelClassName="max-w-3xl">
        <article className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="user-create-title" className="font-display text-2xl">Add user</h2>
            </div>
            <button className="btn-secondary px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={() => setIsCreateModalOpen(false)}>
              Close
            </button>
          </div>

          <form className="mt-5 grid gap-3" onSubmit={handleCreateUser}>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-sm text-sand/70">
                Username
                <input className=" field px-3 py-2 text-sm" value={newUser.username} onChange={(event) => setNewUser((current) => ({ ...current, username: sanitizeUsernameInput(event.target.value) }))} minLength={4} maxLength={16} pattern="[a-z0-9]{4,16}" />
              </label>
              <label className="grid gap-1 text-sm text-sand/70">
                Email
                <input className=" field px-3 py-2 text-sm" type="email" value={newUser.email} onChange={(event) => setNewUser((current) => ({ ...current, email: event.target.value }))} />
              </label>
              <div className="md:col-span-2">
                <label className="grid gap-1 text-sm text-sand/70">
                  Password
                  <input className=" field px-3 py-2 text-sm" type={isPasswordVisible ? "text" : "password"} value={newUser.password} onChange={(event) => setNewUser((current) => ({ ...current, password: event.target.value }))} />
                </label>
                <div className="mt-1 flex gap-1">
                  <button className="btn-secondary px-2 py-1 text-sm text-sand/70 transition hover:bg-white/10" type="button" onClick={handleGeneratePassword} disabled={isGeneratingPassword}>
                    {isGeneratingPassword ? (
                      <span className="inline-block h-4 w-4 animate-spin  border-2 border-white/30 border-t-black" />
                    ) : (
                      <span className="bi bi-shuffle inline-block text-sm" />
                    )}
                  </button>
                  <button className="btn-secondary px-2 py-1 text-sm text-sand/70 transition hover:bg-white/10" type="button" onClick={() => setIsPasswordVisible((current) => !current)}>
                    {isPasswordVisible ? (
                      <span className="bi bi-eye-slash inline-block text-sm" />
                    ) : (
                      <span className="bi bi-eye inline-block text-sm" />
                    )}
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-3  border border-white/10 bg-white/10 px-3 py-2 text-sand text-sm text-sand/70 md:col-span-2">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={newUser.is_admin} onChange={(event) => setNewUser((current) => ({ ...current, is_admin: event.target.checked }))} />
                  Admin
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={newUser.is_active} onChange={(event) => setNewUser((current) => ({ ...current, is_active: event.target.checked }))} />
                  Active
                </label>
              </div>
              {!newUser.is_admin && (
                <div className="md:col-span-2">
                  <label className="block text-sm text-sand/70">
                    <span className="mb-2 block font-semibold text-sand">Package</span>
                    <select
                      className="w-full  field px-3 py-2 text-sm"
                      value={newUser.package_id ?? ""}
                      onChange={(event) => setNewUser((current) => ({ ...current, package_id: event.target.value ? Number(event.target.value) : null }))}
                    >
                      {packages.filter((p) => !p.is_admin_package).map((pkg) => (
                        <option key={pkg.id} value={pkg.id}>{pkg.name}</option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
            </div>
            <div>
              <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={isCreatingUser}>
                {isCreatingUser ? "Creating..." : "Create User"}
              </button>
            </div>
          </form>
        </article>
      </Modal>

      {/* View usage modal */}
      <Modal open={isUsageModalOpen} onClose={() => setIsUsageModalOpen(false)} labelledBy="user-usage-title" panelClassName="max-w-3xl">
        <div className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="user-usage-title" className="font-display text-2xl text-sand">
                Usage for {selectedUsageUser?.username}
              </h2>
            </div>
            <button className="btn-secondary px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={() => setIsUsageModalOpen(false)}>
              Close
            </button>
          </div>

          {isLoadingUsage ? (
            <p className="mt-5 text-sm text-sand/60">Loading token usage...</p>
          ) : userTokenUsages[selectedUsageUser?.id ?? -1] ? (
            (() => {
              const usage = userTokenUsages[selectedUsageUser?.id ?? -1];
              return (
                <div className="mt-5 space-y-4">
                  <div className="surface-muted p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-sand/50 uppercase tracking-wide">Token Usage &amp; Estimated Cost</span>
                      <span className="text-sm font-semibold text-sand">
                        ${usage.estimated_cost.toFixed(4)}
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">60 min</div>
                        <div className="text-sm font-semibold text-sand">{formatTokens(usage.last_60_minutes.total_tokens)}</div>
                        <div className="text-[10px] text-sand/50">
                          {formatTokens(usage.last_60_minutes.input_tokens)} / {formatTokens(usage.last_60_minutes.output_tokens)}
                        </div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">24 hrs</div>
                        <div className="text-sm font-semibold text-sand">{formatTokens(usage.last_24_hours.total_tokens)}</div>
                        <div className="text-[10px] text-sand/50">
                          {formatTokens(usage.last_24_hours.input_tokens)} / {formatTokens(usage.last_24_hours.output_tokens)}
                        </div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">7 days</div>
                        <div className="text-sm font-semibold text-sand">{formatTokens(usage.last_7_days.total_tokens)}</div>
                        <div className="text-[10px] text-sand/50">
                          {formatTokens(usage.last_7_days.input_tokens)} / {formatTokens(usage.last_7_days.output_tokens)}
                        </div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">30 days</div>
                        <div className="text-sm font-semibold text-sand">{formatTokens(usage.last_30_days.total_tokens)}</div>
                        <div className="text-[10px] text-sand/50">
                          {formatTokens(usage.last_30_days.input_tokens)} / {formatTokens(usage.last_30_days.output_tokens)}
                        </div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">Forever</div>
                        <div className="text-sm font-semibold text-sand">{formatTokens(usage.forever.total_tokens)}</div>
                        <div className="text-[10px] text-sand/50">
                          {formatTokens(usage.forever.input_tokens)} / {formatTokens(usage.forever.output_tokens)}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="surface-muted p-4">
                    <span className="text-xs font-semibold text-sand/50 uppercase tracking-wide">Web Search Usage</span>
                    <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">60 min</div>
                        <div className="text-sm font-semibold text-sand">{usage.last_60_minutes.web_searches}</div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">24 hrs</div>
                        <div className="text-sm font-semibold text-sand">{usage.last_24_hours.web_searches}</div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">7 days</div>
                        <div className="text-sm font-semibold text-sand">{usage.last_7_days.web_searches}</div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">30 days</div>
                        <div className="text-sm font-semibold text-sand">{usage.last_30_days.web_searches}</div>
                      </div>
                      <div className="surface-muted px-2 py-1.5 text-center">
                        <div className="text-[10px] uppercase tracking-wide text-sand/50">Forever</div>
                        <div className="text-sm font-semibold text-sand">{usage.forever.web_searches}</div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()
          ) : (
            <p className="mt-5 text-sm text-sand/60">No usage data available for this user.</p>
          )}
        </div>
      </Modal>

      {/* Update email modal */}
      <Modal open={isEmailModalOpen} onClose={() => setIsEmailModalOpen(false)} labelledBy="update-email-title" panelClassName="max-w-md">
        <div className="p-5">
          <div className="flex items-start justify-between">
            <h2 id="update-email-title" className="font-display text-xl">Update email for {selectedEmailUser?.username}</h2>
            <button
              type="button"
              onClick={() => setIsEmailModalOpen(false)}
              className="shrink-0  p-1 text-sand/45 transition hover:bg-white/10 hover:text-sand"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <form className="mt-5 space-y-4" onSubmit={handleUpdateEmail}>
            <label className="block text-sm text-sand/70">
              <span className="mb-2 block font-semibold text-sand">Email</span>
              <input
                className="w-full  field px-4 py-3 outline-none transition focus:border-white/25"
                type="email"
                value={emailValue}
                onChange={(event) => setEmailValue(event.target.value)}
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

      {/* Update password modal */}
      <Modal open={isPasswordModalOpen} onClose={() => setIsPasswordModalOpen(false)} labelledBy="update-password-title" panelClassName="max-w-md">
        <div className="p-5">
          <div className="flex items-start justify-between">
            <h2 id="update-password-title" className="font-display text-xl">Update password for {selectedPasswordUser?.username}</h2>
            <button
              type="button"
              onClick={() => setIsPasswordModalOpen(false)}
              className="shrink-0  p-1 text-sand/45 transition hover:bg-white/10 hover:text-sand"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <form className="mt-5 space-y-4" onSubmit={handleUpdatePassword}>
            <label className="block text-sm text-sand/70">
              <span className="mb-2 block font-semibold text-sand">New password</span>
              <input
                className="w-full  field px-4 py-3 outline-none transition focus:border-white/25"
                type="password"
                value={passwordValue}
                onChange={(event) => setPasswordValue(event.target.value)}
                autoComplete="new-password"
                placeholder="Enter a new password"
              />
            </label>
            <label className="block text-sm text-sand/70">
              <span className="mb-2 block font-semibold text-sand">Confirm new password</span>
              <input
                className="w-full  field px-4 py-3 outline-none transition focus:border-white/25"
                type="password"
                value={confirmPasswordValue}
                onChange={(event) => setConfirmPasswordValue(event.target.value)}
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

      {/* Delete confirmation modal */}
      <Modal open={isDeleteModalOpen} onClose={() => setIsDeleteModalOpen(false)} labelledBy="delete-user-title">
        <div className="p-5">
          <div className="flex items-start justify-between">
            <h2 id="delete-user-title" className="font-display text-xl">Delete user</h2>
            <button
              type="button"
              onClick={() => setIsDeleteModalOpen(false)}
              className="shrink-0  p-1 text-sand/45 transition hover:bg-white/10 hover:text-sand"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <div className="mt-5">
            <p className="text-sm text-sand/70">
              Are you sure you want to delete <span className="font-semibold text-sand">{selectedDeleteUser?.username}</span>? This action cannot be undone.
            </p>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <button
              className=" btn-secondary px-4 py-3 text-sm font-semibold"
              type="button"
              onClick={() => setIsDeleteModalOpen(false)}
            >
              Cancel
            </button>
            <button
              className=" bg-red-600 px-4 py-3 font-semibold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              onClick={handleDeleteUser}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete user"}
            </button>
          </div>
        </div>
      </Modal>
      </section>
    </SettingsLayout>
  );
}
