import { FormEvent, useEffect, useMemo, useState } from "react";
import { apiGet, apiPatch } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { AppSettingsRecord } from "../lib/records";

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

const DEFAULT_SETTINGS: AppSettingsRecord = {
  users_can_register: false,
  sitename: "LmPanel",
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
};

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

export default function UsageLimitsPage() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [draft, setDraft] = useState({
    usage_limit_tokens_60_minutes: "0",
    usage_limit_tokens_24_hours: "0",
    usage_limit_tokens_7_days: "0",
    usage_limit_tokens_30_days: "0",
    usage_limit_tools_60_minutes: "0",
    usage_limit_tools_24_hours: "0",
    usage_limit_tools_7_days: "0",
    usage_limit_tools_30_days: "0",
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!token) {
      return;
    }

    void loadPageData(token);
  }, [token]);

  async function loadPageData(activeToken: string) {
    setIsLoading(true);
    try {
      const settingsResponse = await apiGet<AppSettingsRecord>("/api/admin/settings", activeToken);
      setDraft({
        usage_limit_tokens_60_minutes: String(settingsResponse.usage_limit_tokens_60_minutes ?? 0),
        usage_limit_tokens_24_hours: String(settingsResponse.usage_limit_tokens_24_hours ?? 0),
        usage_limit_tokens_7_days: String(settingsResponse.usage_limit_tokens_7_days ?? 0),
        usage_limit_tokens_30_days: String(settingsResponse.usage_limit_tokens_30_days ?? 0),
        usage_limit_tools_60_minutes: String(settingsResponse.usage_limit_tools_60_minutes ?? 0),
        usage_limit_tools_24_hours: String(settingsResponse.usage_limit_tools_24_hours ?? 0),
        usage_limit_tools_7_days: String(settingsResponse.usage_limit_tools_7_days ?? 0),
        usage_limit_tools_30_days: String(settingsResponse.usage_limit_tools_30_days ?? 0),
      });
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load usage limits");
    } finally {
      setIsLoading(false);
    }
  }

  const parsedTokenLimits = useMemo((): { valid: false; message: string } | { valid: true; values: {
    usage_limit_tokens_60_minutes: number;
    usage_limit_tokens_24_hours: number;
    usage_limit_tokens_7_days: number;
    usage_limit_tokens_30_days: number;
  } } => {
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
      return { valid: false, message: "Token limits must be whole numbers of zero or greater." };
    }

    const values = {
      usage_limit_tokens_60_minutes,
      usage_limit_tokens_24_hours,
      usage_limit_tokens_7_days,
      usage_limit_tokens_30_days,
    };

    const validationMessage = validateTokenUsageLimits(values);
    if (validationMessage) {
      return { valid: false, message: validationMessage };
    }

    return { valid: true, values };
  }, [draft]);

  const parsedToolLimits = useMemo((): { valid: false; message: string } | { valid: true; values: {
    usage_limit_tools_60_minutes: number;
    usage_limit_tools_24_hours: number;
    usage_limit_tools_7_days: number;
    usage_limit_tools_30_days: number;
  } } => {
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
      return { valid: false, message: "Tool usage limits must be whole numbers of zero or greater." };
    }

    const values = {
      usage_limit_tools_60_minutes,
      usage_limit_tools_24_hours,
      usage_limit_tools_7_days,
      usage_limit_tools_30_days,
    };

    const validationMessage = validateToolUsageLimits(values);
    if (validationMessage) {
      return { valid: false, message: validationMessage };
    }

    return { valid: true, values };
  }, [draft]);

  const allValid = parsedTokenLimits.valid && parsedToolLimits.valid;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !allValid) {
      if (!parsedTokenLimits.valid) {
        showError(parsedTokenLimits.message);
      }
      if (!parsedToolLimits.valid) {
        showError(parsedToolLimits.message);
      }
      return;
    }

    setIsSaving(true);
    try {
      const response = await apiPatch<
        Pick<
          AppSettingsRecord,
          | "usage_limit_tokens_60_minutes"
          | "usage_limit_tokens_24_hours"
          | "usage_limit_tokens_7_days"
          | "usage_limit_tokens_30_days"
          | "usage_limit_tools_60_minutes"
          | "usage_limit_tools_24_hours"
          | "usage_limit_tools_7_days"
          | "usage_limit_tools_30_days"
        >,
        AppSettingsRecord
      >("/api/admin/settings", {
        ...parsedTokenLimits.values,
        ...parsedToolLimits.values,
      }, token);
      setDraft({
        usage_limit_tokens_60_minutes: String(response.usage_limit_tokens_60_minutes ?? 0),
        usage_limit_tokens_24_hours: String(response.usage_limit_tokens_24_hours ?? 0),
        usage_limit_tokens_7_days: String(response.usage_limit_tokens_7_days ?? 0),
        usage_limit_tokens_30_days: String(response.usage_limit_tokens_30_days ?? 0),
        usage_limit_tools_60_minutes: String(response.usage_limit_tools_60_minutes ?? 0),
        usage_limit_tools_24_hours: String(response.usage_limit_tools_24_hours ?? 0),
        usage_limit_tools_7_days: String(response.usage_limit_tools_7_days ?? 0),
        usage_limit_tools_30_days: String(response.usage_limit_tools_30_days ?? 0),
      });
      showSuccess("Usage limits updated.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to save usage limits");
    } finally {
      setIsSaving(false);
    }
  }

  const tokenLimitsEnabled = parsedTokenLimits.valid && (
    parsedTokenLimits.values.usage_limit_tokens_60_minutes > 0
    || parsedTokenLimits.values.usage_limit_tokens_24_hours > 0
    || parsedTokenLimits.values.usage_limit_tokens_7_days > 0
    || parsedTokenLimits.values.usage_limit_tokens_30_days > 0
  );

  const toolLimitsEnabled = parsedToolLimits.valid && (
    parsedToolLimits.values.usage_limit_tools_60_minutes > 0
    || parsedToolLimits.values.usage_limit_tools_24_hours > 0
    || parsedToolLimits.values.usage_limit_tools_7_days > 0
    || parsedToolLimits.values.usage_limit_tools_30_days > 0
  );

  if (isLoading) {
    return <div className=" px-4 py-8 text-sm text-sand/55">Loading usage limits...</div>;
  }

  return (
    <form className="grid gap-4" onSubmit={handleSubmit}>
      <section className="-[28px] p-6">
        <h2 className="font-display text-2xl text-sand">Usage Limits</h2>
        <p className="mt-2 max-w-3xl text-sm text-sand/60">
          Set per-account limits for standard users. Admin users are not limited. Use zero to disable a time window.
          When every limit is zero, usage is unlimited for everyone.
        </p>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {TOKEN_PERIOD_FIELDS.map((period) => (
            <div key={period.key}>
              <label htmlFor={period.key} className="block text-sm font-medium text-sand/70">
                {period.label}
              </label>
              <input
                id={period.key}
                type="number"
                min={0}
                step={1}
                value={draft[period.key]}
                onChange={(event) => setDraft((current) => ({ ...current, [period.key]: event.target.value }))}
                className="mt-1 w-full  border border-white/10 bg-white/10 px-3 py-2 text-sand.5 text-sand outline-none focus:border-white/30"
              />
              <p className="mt-1 text-xs text-sand/50">0 = unlimited for this window</p>
            </div>
          ))}
        </div>

        <div className="mt-8">
          <h3 className="font-display text-xl text-sand">Tool Usage Limits</h3>
          <p className="mt-2 max-w-3xl text-sm text-sand/60">
            Set per-account web search tool call limits for standard users. Admin users are not limited.
            Use zero to disable a time window. When every tool limit is zero, web search usage is unlimited.
            Users who hit a tool limit cannot use web search but can still use other tools, chat, and the API (assuming within token limits).
          </p>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {TOOL_PERIOD_FIELDS.map((period) => (
              <div key={period.key}>
                <label htmlFor={period.key} className="block text-sm font-medium text-sand/70">
                  {period.label}
                </label>
                <input
                  id={period.key}
                  type="number"
                  min={0}
                  step={1}
                  value={draft[period.key]}
                  onChange={(event) => setDraft((current) => ({ ...current, [period.key]: event.target.value }))}
                  className="mt-1 w-full  border border-white/10 bg-white/10 px-3 py-2 text-sand.5 text-sand outline-none focus:border-white/30"
                />
                <p className="mt-1 text-xs text-sand/50">0 = unlimited for this window</p>
              </div>
            ))}
          </div>
        </div>

        {!parsedTokenLimits.valid ? (
          <p className="mt-4 text-sm text-[#b42318]">{parsedTokenLimits.message}</p>
        ) : null}
        {!parsedToolLimits.valid ? (
          <p className="mt-4 text-sm text-[#b42318]">{parsedToolLimits.message}</p>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-sand/55">
            {tokenLimitsEnabled && toolLimitsEnabled
              ? "Token and tool limits are active for standard users."
              : tokenLimitsEnabled
                ? "Token limits are active for standard users."
                : toolLimitsEnabled
                  ? "Tool usage limits are active for standard users."
                  : "All limits are currently disabled (unlimited usage)."}
          </p>
          <button
            type="submit"
            disabled={isSaving || !allValid}
            className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas hover:bg-black/85 disabled:opacity-50"
          >
            {isSaving ? "Saving..." : "Save usage limits"}
          </button>
        </div>
      </section>
    </form>
  );
}
