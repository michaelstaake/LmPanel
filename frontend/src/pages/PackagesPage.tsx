import { FormEvent, useEffect, useState } from "react";
import Modal from "../components/ui/Modal";
import { apiGet, apiDelete, apiPatch, apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { PackageRecord } from "../lib/records";
import SettingsLayout from "./SettingsLayout";

const TOKEN_PERIOD_FIELDS = [
  { key: "usage_limit_tokens_60_minutes" as const, label: "60 Minutes" },
  { key: "usage_limit_tokens_24_hours" as const, label: "24 Hours" },
  { key: "usage_limit_tokens_7_days" as const, label: "7 Days" },
  { key: "usage_limit_tokens_30_days" as const, label: "30 Days" },
];

const TOOL_PERIOD_FIELDS = [
  { key: "usage_limit_tools_60_minutes" as const, label: "60 Minutes" },
  { key: "usage_limit_tools_24_hours" as const, label: "24 Hours" },
  { key: "usage_limit_tools_7_days" as const, label: "7 Days" },
  { key: "usage_limit_tools_30_days" as const, label: "30 Days" },
];

function parseLimitValue(rawValue: string): number | null {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return 0;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0 || !Number.isInteger(parsed)) {
    return null;
  }
  return parsed;
}

function validatePackageName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) {
    return "Package name is required";
  }
  if (!/^[a-zA-Z0-9]+$/.test(trimmed)) {
    return "Package name can only contain letters and numbers";
  }
  return null;
}

function validateTokenUsageLimits(values: {
  usage_limit_tokens_60_minutes: number;
  usage_limit_tokens_24_hours: number;
  usage_limit_tokens_7_days: number;
  usage_limit_tokens_30_days: number;
}): string | null {
  const ordered = [
    { label: "60 Minutes", value: values.usage_limit_tokens_60_minutes },
    { label: "24 Hours", value: values.usage_limit_tokens_24_hours },
    { label: "7 Days", value: values.usage_limit_tokens_7_days },
    { label: "30 Days", value: values.usage_limit_tokens_30_days },
  ];
  const enabled = ordered.filter((period) => period.value > 0);
  for (let shorterIndex = 0; shorterIndex < enabled.length; shorterIndex += 1) {
    for (let longerIndex = shorterIndex + 1; longerIndex < enabled.length; longerIndex += 1) {
      if (enabled[longerIndex].value < enabled[shorterIndex].value) {
        return `The ${enabled[longerIndex].label} token limit cannot be lower than the ${enabled[shorterIndex].label} limit when both are enabled.`;
      }
    }
  }
  return null;
}

function validateToolUsageLimits(values: {
  usage_limit_tools_60_minutes: number;
  usage_limit_tools_24_hours: number;
  usage_limit_tools_7_days: number;
  usage_limit_tools_30_days: number;
}): string | null {
  const ordered = [
    { label: "60 Minutes", value: values.usage_limit_tools_60_minutes },
    { label: "24 Hours", value: values.usage_limit_tools_24_hours },
    { label: "7 Days", value: values.usage_limit_tools_7_days },
    { label: "30 Days", value: values.usage_limit_tools_30_days },
  ];
  const enabled = ordered.filter((period) => period.value > 0);
  for (let shorterIndex = 0; shorterIndex < enabled.length; shorterIndex += 1) {
    for (let longerIndex = shorterIndex + 1; longerIndex < enabled.length; longerIndex += 1) {
      if (enabled[longerIndex].value < enabled[shorterIndex].value) {
        return `The ${enabled[longerIndex].label} tool usage limit cannot be lower than the ${enabled[shorterIndex].label} limit when both are enabled.`;
      }
    }
  }
  return null;
}

type PackageDraft = {
  name: string;
  is_admin_package: boolean;
  usage_limit_tokens_60_minutes: string;
  usage_limit_tokens_24_hours: string;
  usage_limit_tokens_7_days: string;
  usage_limit_tokens_30_days: string;
  usage_limit_tools_60_minutes: string;
  usage_limit_tools_24_hours: string;
  usage_limit_tools_7_days: string;
  usage_limit_tools_30_days: string;
};

type EditPackageDraft = {
  name: string;
  is_admin_package: boolean;
  usage_limit_tokens_60_minutes: string;
  usage_limit_tokens_24_hours: string;
  usage_limit_tokens_7_days: string;
  usage_limit_tokens_30_days: string;
  usage_limit_tools_60_minutes: string;
  usage_limit_tools_24_hours: string;
  usage_limit_tools_7_days: string;
  usage_limit_tools_30_days: string;
};

export default function PackagesPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [packages, setPackages] = useState<PackageRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [createNameError, setCreateNameError] = useState<string | null>(null);
  const [editNameError, setEditNameError] = useState<string | null>(null);

  // Create modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<PackageDraft>({
    name: "",
    is_admin_package: false,
    usage_limit_tokens_60_minutes: "0",
    usage_limit_tokens_24_hours: "0",
    usage_limit_tokens_7_days: "0",
    usage_limit_tokens_30_days: "0",
    usage_limit_tools_60_minutes: "0",
    usage_limit_tools_24_hours: "0",
    usage_limit_tools_7_days: "0",
    usage_limit_tools_30_days: "0",
  });

  // Edit modal
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingPackage, setEditingPackage] = useState<PackageRecord | null>(null);
  const [editDraft, setEditDraft] = useState<EditPackageDraft>({
    name: "",
    is_admin_package: false,
    usage_limit_tokens_60_minutes: "0",
    usage_limit_tokens_24_hours: "0",
    usage_limit_tokens_7_days: "0",
    usage_limit_tokens_30_days: "0",
    usage_limit_tools_60_minutes: "0",
    usage_limit_tools_24_hours: "0",
    usage_limit_tools_7_days: "0",
    usage_limit_tools_30_days: "0",
  });

  // Delete modal
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deletingPackage, setDeletingPackage] = useState<PackageRecord | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    void loadPackages(token);
  }, [token]);

  async function loadPackages(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<PackageRecord[]>("/api/admin/packages", activeToken);
      setPackages(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load packages");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }

    if (createDraft.is_admin_package) {
      showError("Cannot create admin packages. The admin package is managed automatically.");
      return;
    }

    const packageNameError = validatePackageName(createDraft.name);
    if (packageNameError !== null) {
      setCreateNameError(packageNameError);
      return;
    }

    const existingPackage = packages.find((p) => p.name.toLowerCase() === createDraft.name.trim().toLowerCase());
    if (existingPackage) {
      setCreateNameError("A package with that name already exists.");
      return;
    }

    const tokenLimitsError = validateTokenLimits(createDraft);
    const toolLimitsError = validateToolLimits(createDraft);
    if (tokenLimitsError !== null || toolLimitsError !== null) {
      if (tokenLimitsError !== null) {
        showError(tokenLimitsError);
      }
      if (toolLimitsError !== null) {
        showError(toolLimitsError);
      }
      return;
    }

    setIsCreating(true);
    try {
      const payload: Omit<PackageRecord, "id"> = {
        name: createDraft.name,
        is_admin_package: createDraft.is_admin_package,
        is_default_package: false,
        usage_limit_tokens_60_minutes: Number(createDraft.usage_limit_tokens_60_minutes),
        usage_limit_tokens_24_hours: Number(createDraft.usage_limit_tokens_24_hours),
        usage_limit_tokens_7_days: Number(createDraft.usage_limit_tokens_7_days),
        usage_limit_tokens_30_days: Number(createDraft.usage_limit_tokens_30_days),
        usage_limit_tools_60_minutes: Number(createDraft.usage_limit_tools_60_minutes),
        usage_limit_tools_24_hours: Number(createDraft.usage_limit_tools_24_hours),
        usage_limit_tools_7_days: Number(createDraft.usage_limit_tools_7_days),
        usage_limit_tools_30_days: Number(createDraft.usage_limit_tools_30_days),
      };
      const response = await apiPost<Omit<PackageRecord, "id">, { status: string; package: PackageRecord }>("/api/admin/packages", payload, token);
      setPackages((current) => [...current, response.package].sort((a, b) => a.name.localeCompare(b.name)));
      setCreateDraft({
        name: "",
        is_admin_package: false,
        usage_limit_tokens_60_minutes: "0",
        usage_limit_tokens_24_hours: "0",
        usage_limit_tokens_7_days: "0",
        usage_limit_tokens_30_days: "0",
        usage_limit_tools_60_minutes: "0",
        usage_limit_tools_24_hours: "0",
        usage_limit_tools_7_days: "0",
        usage_limit_tools_30_days: "0",
      });
      setCreateNameError(null);
      setIsCreateModalOpen(false);
      showSuccess(`Created package ${response.package.name}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Package creation failed");
      setCreateNameError(null);
    } finally {
      setIsCreating(false);
    }
  }

  async function handleEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !editingPackage) {
      return;
    }

    if (editingPackage.is_admin_package) {
      showError("Cannot edit the admin package.");
      return;
    }

    if (!editingPackage.is_default_package) {
      const packageNameError = validatePackageName(editDraft.name);
      if (packageNameError !== null) {
        setEditNameError(packageNameError);
        return;
      }

      const existingPackage = packages.find((p) => p.id !== editingPackage.id && p.name.toLowerCase() === editDraft.name.trim().toLowerCase());
      if (existingPackage) {
        setEditNameError("A package with that name already exists.");
        return;
      }
    }

    const tokenLimitsError = validateTokenLimits(editDraft);
    const toolLimitsError = validateToolLimits(editDraft);
    if (tokenLimitsError !== null || toolLimitsError !== null) {
      if (tokenLimitsError !== null) {
        showError(tokenLimitsError);
      }
      if (toolLimitsError !== null) {
        showError(toolLimitsError);
      }
      return;
    }

    setIsSaving(true);
    try {
      const payload: Omit<PackageRecord, "id"> = {
        name: editingPackage.is_default_package ? editingPackage.name : editDraft.name,
        is_admin_package: editingPackage.is_default_package ? editingPackage.is_admin_package : editDraft.is_admin_package,
        is_default_package: editingPackage.is_default_package,
        usage_limit_tokens_60_minutes: Number(editDraft.usage_limit_tokens_60_minutes),
        usage_limit_tokens_24_hours: Number(editDraft.usage_limit_tokens_24_hours),
        usage_limit_tokens_7_days: Number(editDraft.usage_limit_tokens_7_days),
        usage_limit_tokens_30_days: Number(editDraft.usage_limit_tokens_30_days),
        usage_limit_tools_60_minutes: Number(editDraft.usage_limit_tools_60_minutes),
        usage_limit_tools_24_hours: Number(editDraft.usage_limit_tools_24_hours),
        usage_limit_tools_7_days: Number(editDraft.usage_limit_tools_7_days),
        usage_limit_tools_30_days: Number(editDraft.usage_limit_tools_30_days),
      };
      const response = await apiPatch<Omit<PackageRecord, "id">, { status: string; package: PackageRecord }>(`/api/admin/packages/${editingPackage.id}`, payload, token);
      setPackages((current) => current.map((p) => (p.id === editingPackage.id ? response.package : p)));
      setIsEditModalOpen(false);
      setEditingPackage(null);
      setEditNameError(null);
      showSuccess(`Updated package ${response.package.name}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Package update failed");
      setEditNameError(null);
    } finally {
      setIsSaving(false);
    }
  }

  function openEditModal(pkg: PackageRecord) {
    if (pkg.is_admin_package) {
      showError("Cannot edit the admin package.");
      return;
    }
    setEditingPackage(pkg);
    setEditDraft({
      name: pkg.name,
      is_admin_package: pkg.is_admin_package,
      usage_limit_tokens_60_minutes: String(pkg.usage_limit_tokens_60_minutes),
      usage_limit_tokens_24_hours: String(pkg.usage_limit_tokens_24_hours),
      usage_limit_tokens_7_days: String(pkg.usage_limit_tokens_7_days),
      usage_limit_tokens_30_days: String(pkg.usage_limit_tokens_30_days),
      usage_limit_tools_60_minutes: String(pkg.usage_limit_tools_60_minutes),
      usage_limit_tools_24_hours: String(pkg.usage_limit_tools_24_hours),
      usage_limit_tools_7_days: String(pkg.usage_limit_tools_7_days),
      usage_limit_tools_30_days: String(pkg.usage_limit_tools_30_days),
    });
    setIsEditModalOpen(true);
  }

  function openDeleteModal(pkg: PackageRecord) {
    if (pkg.is_admin_package || pkg.is_default_package) {
      showError("Cannot delete the admin or default package.");
      return;
    }
    setDeletingPackage(pkg);
    setIsDeleteModalOpen(true);
  }

  async function handleDelete() {
    if (!token || !deletingPackage) {
      return;
    }
    setIsDeleting(true);
    try {
      await apiDelete(`/api/admin/packages/${deletingPackage.id}`, token);
      setPackages((current) => current.filter((p) => p.id !== deletingPackage.id));
      setIsDeleteModalOpen(false);
      setDeletingPackage(null);
      showSuccess(`Deleted package ${deletingPackage.name}.`);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Package deletion failed");
    } finally {
      setIsDeleting(false);
    }
  }

  function validateTokenLimits(draft: PackageDraft | EditPackageDraft): string | null {
    const usage_limit_tokens_60_minutes = parseLimitValue(draft.usage_limit_tokens_60_minutes);
    const usage_limit_tokens_24_hours = parseLimitValue(draft.usage_limit_tokens_24_hours);
    const usage_limit_tokens_7_days = parseLimitValue(draft.usage_limit_tokens_7_days);
    const usage_limit_tokens_30_days = parseLimitValue(draft.usage_limit_tokens_30_days);

    if (
      usage_limit_tokens_60_minutes === null
      || usage_limit_tokens_24_hours === null
      || usage_limit_tokens_7_days === null
      || usage_limit_tokens_30_days === null
    ) {
      return "Token limits must be whole numbers of zero or greater.";
    }

    return validateTokenUsageLimits({
      usage_limit_tokens_60_minutes,
      usage_limit_tokens_24_hours,
      usage_limit_tokens_7_days,
      usage_limit_tokens_30_days,
    });
  }

  function validateToolLimits(draft: PackageDraft | EditPackageDraft): string | null {
    const usage_limit_tools_60_minutes = parseLimitValue(draft.usage_limit_tools_60_minutes);
    const usage_limit_tools_24_hours = parseLimitValue(draft.usage_limit_tools_24_hours);
    const usage_limit_tools_7_days = parseLimitValue(draft.usage_limit_tools_7_days);
    const usage_limit_tools_30_days = parseLimitValue(draft.usage_limit_tools_30_days);

    if (
      usage_limit_tools_60_minutes === null
      || usage_limit_tools_24_hours === null
      || usage_limit_tools_7_days === null
      || usage_limit_tools_30_days === null
    ) {
      return "Tool usage limits must be whole numbers of zero or greater.";
    }

    return validateToolUsageLimits({
      usage_limit_tools_60_minutes,
      usage_limit_tools_24_hours,
      usage_limit_tools_7_days,
      usage_limit_tools_30_days,
    });
  }

  const adminPackage = packages.find((p) => p.is_admin_package);
  const standardPackages = packages.filter((p) => !p.is_admin_package);

  return (
    <SettingsLayout title="Packages">
      <section className="grid gap-4">
      <article>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl">Packages</h2>
            <p className="mt-2 max-w-3xl text-sm text-sand/60">
              Packages define usage limits for users. Admin users are assigned the Unlimited package.
              Standard users are assigned the Default package. Create custom packages for specific usage tiers.
            </p>
          </div>
          <button
            className=" border border-white/15 bg-white/10 px-4 py-3 text-sand text-sm font-semibold text-sand transition hover:bg-white/10"
            type="button"
            onClick={() => setIsCreateModalOpen(true)}
          >
            Add package
          </button>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {packages.map((pkg) => (
            <div key={pkg.id} className=" p-4">
              <div className="flex items-center justify-between">
                <h3 className="font-display text-lg text-sand">{pkg.name}</h3>
                {pkg.is_admin_package ? (
                  <span className=" bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">Admin</span>
                ) : pkg.is_default_package ? (
                  <span className=" bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-800">Default</span>
                ) : null}
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {!pkg.is_admin_package ? (
                  <>
                    <button
                      className=" border border-white/15 bg-white px-2.5 py-1.5 text-xs font-semibold text-sand transition hover:bg-white/10"
                      type="button"
                      onClick={() => openEditModal(pkg)}
                    >
                      Edit
                    </button>
                    {!pkg.is_default_package ? (
                      <button
                        className=" border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs font-semibold text-red-600 transition hover:bg-red-100"
                        type="button"
                        onClick={() => openDeleteModal(pkg)}
                      >
                        Delete
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <p className="col-span-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-sand/40">Tokens</p>
                {TOKEN_PERIOD_FIELDS.map((period) => (
                  <div key={period.key} className=" bg-sand/60 px-2 py-1.5 text-center">
                    <div className="text-[10px] uppercase tracking-wide text-sand/50">{period.label}</div>
                    <div className="text-sm font-semibold text-sand">
                      {pkg[period.key] === 0 ? "Unlimited" : pkg[period.key].toLocaleString()}
                    </div>
                  </div>
                ))}
                <p className="col-span-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-sand/40">Web Search</p>
                {TOOL_PERIOD_FIELDS.map((period) => (
                  <div key={period.key} className=" bg-sand/60 px-2 py-1.5 text-center">
                    <div className="text-[10px] uppercase tracking-wide text-sand/50">{period.label}</div>
                    <div className="text-sm font-semibold text-sand">
                      {pkg[period.key] === 0 ? "Unlimited" : pkg[period.key].toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {isLoading ? <p className=" border border-white/10 bg-white px-4 py-6 text-sm text-sand/60">Loading packages...</p> : null}
          {!isLoading && packages.length === 0 ? (
            <p className=" border border-dashed border-white/15 px-4 py-6 text-sm text-sand/60">No packages created yet.</p>
          ) : null}
        </div>
      </article>

      {/* Create package modal */}
      <Modal open={isCreateModalOpen} onClose={() => setIsCreateModalOpen(false)} labelledBy="package-create-title" panelClassName="max-w-2xl">
        <article className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="package-create-title" className="font-display text-2xl">Add package</h2>
            </div>
            <button className=" border border-white/15 bg-white px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={() => setIsCreateModalOpen(false)}>
              Close
            </button>
          </div>

          <form className="mt-5 grid gap-3" onSubmit={handleCreate}>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-sm text-sand/70">
                Name
                <input
                  className=" border border-white/15 bg-white/10 px-3 text-sand py-2 text-sm"
                  value={createDraft.name}
                  onChange={(event) => {
                    setCreateDraft((current) => ({ ...current, name: event.target.value }));
                    setCreateNameError(null);
                  }}
                  required
                />
                {createNameError ? <span className="text-xs text-red-600">{createNameError}</span> : null}
              </label>
              <div className="md:col-span-2">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sand/40">Tokens</p>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  {TOKEN_PERIOD_FIELDS.map((period) => (
                    <div key={period.key}>
                      <label className="block text-xs text-sand/70">{period.label}</label>
                      <input className="w-full  border border-white/15 bg-white px-2 py-1.5 text-sm" type="number" min={0} step={1} value={createDraft[period.key]} onChange={(event) => setCreateDraft((current) => ({ ...current, [period.key]: event.target.value }))} />
                      <p className="mt-0.5 text-[10px] text-sand/50">0 = unlimited</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="md:col-span-2">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sand/40">Web Search</p>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  {TOOL_PERIOD_FIELDS.map((period) => (
                    <div key={period.key}>
                      <label className="block text-xs text-sand/70">{period.label}</label>
                      <input className="w-full  border border-white/15 bg-white px-2 py-1.5 text-sm" type="number" min={0} step={1} value={createDraft[period.key]} onChange={(event) => setCreateDraft((current) => ({ ...current, [period.key]: event.target.value }))} />
                      <p className="mt-0.5 text-[10px] text-sand/50">0 = unlimited</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div>
              <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={isCreating}>
                {isCreating ? "Creating..." : "Create Package"}
              </button>
            </div>
          </form>
        </article>
      </Modal>

      {/* Edit package modal */}
      <Modal open={isEditModalOpen} onClose={() => setIsEditModalOpen(false)} labelledBy="package-edit-title" panelClassName="max-w-2xl">
        <article className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="package-edit-title" className="font-display text-2xl">Edit package</h2>
            </div>
            <button className=" border border-white/15 bg-white px-4 py-2 text-sm font-semibold text-sand" type="button" onClick={() => setIsEditModalOpen(false)}>
              Close
            </button>
          </div>

          <form className="mt-5 grid gap-3" onSubmit={handleEdit}>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-sm text-sand/70">
                Name
                <input
                  className=" border border-white/15 bg-white/10 px-3 text-sand py-2 text-sm disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-sand/50"
                  value={editDraft.name}
                  onChange={(event) => {
                    setEditDraft((current) => ({ ...current, name: event.target.value }));
                    setEditNameError(null);
                  }}
                  disabled={editingPackage?.is_default_package}
                  required
                />
                {editingPackage?.is_default_package ? (
                  <span className="text-xs text-sand/50">The default package name cannot be changed.</span>
                ) : null}
                {editNameError ? <span className="text-xs text-red-600">{editNameError}</span> : null}
              </label>
              <div className="md:col-span-2">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sand/40">Tokens</p>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  {TOKEN_PERIOD_FIELDS.map((period) => (
                    <div key={period.key}>
                      <label className="block text-xs text-sand/70">{period.label}</label>
                      <input className="w-full  border border-white/15 bg-white px-2 py-1.5 text-sm" type="number" min={0} step={1} value={editDraft[period.key]} onChange={(event) => setEditDraft((current) => ({ ...current, [period.key]: event.target.value }))} />
                      <p className="mt-0.5 text-[10px] text-sand/50">0 = unlimited</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="md:col-span-2">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sand/40">Web Search</p>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  {TOOL_PERIOD_FIELDS.map((period) => (
                    <div key={period.key}>
                      <label className="block text-xs text-sand/70">{period.label}</label>
                      <input className="w-full  border border-white/15 bg-white px-2 py-1.5 text-sm" type="number" min={0} step={1} value={editDraft[period.key]} onChange={(event) => setEditDraft((current) => ({ ...current, [period.key]: event.target.value }))} />
                      <p className="mt-0.5 text-[10px] text-sand/50">0 = unlimited</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div>
              <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={isSaving}>
                {isSaving ? "Saving..." : "Save Package"}
              </button>
            </div>
          </form>
        </article>
      </Modal>

      {/* Delete confirmation modal */}
      <Modal open={isDeleteModalOpen} onClose={() => setIsDeleteModalOpen(false)} labelledBy="delete-package-title">
        <div className="p-5">
          <div className="flex items-start justify-between">
            <h2 id="delete-package-title" className="font-display text-xl">Delete package</h2>
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
              Are you sure you want to delete <span className="font-semibold text-sand">{deletingPackage?.name}</span>? This action cannot be undone.
            </p>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <button
              className=" border border-white/15 bg-white/10 px-4 py-3 text-sand text-sm font-semibold text-sand transition hover:bg-white/10"
              type="button"
              onClick={() => setIsDeleteModalOpen(false)}
            >
              Cancel
            </button>
            <button
              className=" bg-red-600 px-4 py-3 font-semibold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete package"}
            </button>
          </div>
        </div>
      </Modal>
      </section>
    </SettingsLayout>
  );
}
