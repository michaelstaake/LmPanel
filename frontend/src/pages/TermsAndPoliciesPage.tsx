import { FormEvent, useEffect, useState } from "react";
import CodeEditor from "../components/ui/CodeEditor";
import MarkdownRenderer from "../components/ui/MarkdownRenderer";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { apiGet, apiPatch } from "../lib/api";
import SettingsLayout from "./SettingsLayout";

const MAX_TERMS_CONTENT_LENGTH = 50000;

type TermsSettings = {
  terms_enabled: boolean;
  terms_content: string;
};

export default function TermsAndPoliciesPage() {
  const { token, termsSettings, refreshAuthState } = useAuth();
  const { showError, showSuccess } = useToast();
  const [localSettings, setLocalSettings] = useState<TermsSettings>({
    terms_enabled: false,
    terms_content: "",
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    if (!token) {
      return;
    }
    void loadTermsSettings(token);
  }, [token]);

  async function loadTermsSettings(activeToken: string) {
    setIsLoading(true);
    try {
      const response = await apiGet<TermsSettings>("/api/terms/settings", activeToken);
      setLocalSettings(response);
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load terms and policies settings");
    } finally {
      setIsLoading(false);
    }
  }

  function updateEnabled(enabled: boolean) {
    setLocalSettings((current) => ({ ...current, terms_enabled: enabled }));
  }

  function updateContent(content: string) {
    setLocalSettings((current) => ({ ...current, terms_content: content }));
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!token) {
      return;
    }

    const previousSettings = localSettings;
    setIsSaving(true);
    try {
      const response = await apiPatch<TermsSettings, TermsSettings>("/api/terms/settings", localSettings, token);
      setLocalSettings(response);
      await refreshAuthState();
      showSuccess("Terms and policies updated.");
    } catch (error) {
      setLocalSettings(previousSettings);
      showError(error instanceof Error ? error.message : "Failed to update terms and policies");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <SettingsLayout title="Terms and Policies">
      <form onSubmit={handleSave}>
        <section className="grid gap-4">
        <article>
          <h2 className="font-display text-xl">Terms and Policies</h2>
          <p className="mt-1 text-sm text-sand/65">
            When enabled, users will be prompted to accept the terms and policies before accessing the web interface.
          </p>

          <div className="mt-5 grid gap-3">
            <label className="surface-muted flex items-start justify-between gap-4 px-4 py-4">
              <div>
                <div className="text-sm font-semibold text-sand">Enable terms and policies</div>
                <p className="mt-1 text-sm text-sand/65">
                  Require users to accept the terms and policies before using LmPanel.
                </p>
              </div>
              <input
                type="checkbox"
                checked={localSettings.terms_enabled}
                disabled={isLoading || isSaving}
                onChange={(event) => updateEnabled(event.target.checked)}
                className="mt-1 h-5 w-5 cursor-pointer  border border-white/15 text-sand focus:ring-sand/20"
              />
            </label>

            <div className="surface-muted px-4 py-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-sand">Terms and policies content</div>
                  <p className="mt-1 text-sm text-sand/65">
                    Write your terms and policies in Markdown format.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowPreview(!showPreview)}
                    className=" btn-secondary px-3 py-2 text-sm font-semibold transition hover:border-white/20 hover:bg-white/10"
                    disabled={isLoading || isSaving}
                  >
                    {showPreview ? "Edit" : "Preview"}
                  </button>
                </div>
              </div>

              <div className="mt-3">
                {showPreview ? (
                  <div className="surface p-5">
                    {localSettings.terms_content ? (
                      <MarkdownRenderer content={localSettings.terms_content} />
                    ) : (
                      <p className="text-sm text-sand/50">No content to preview. Add content in the editor.</p>
                    )}
                  </div>
                ) : (
                  <CodeEditor
                    value={localSettings.terms_content}
                    onChange={updateContent}
                    placeholder="Write your terms and policies here..."
                    maxLength={MAX_TERMS_CONTENT_LENGTH}
                    height="24rem"
                  />
                )}
              </div>

              <div className="mt-6 flex justify-end">
                <button
                  type="submit"
                  disabled={isLoading || isSaving}
                  className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas hover:bg-black/85 disabled:opacity-50"
                >
                  {isSaving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        </article>
        </section>
      </form>
    </SettingsLayout>
  );
}
