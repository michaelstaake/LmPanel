import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { apiGet, apiPatch } from "../lib/api";
import SettingsLayout from "./SettingsLayout";

export default function KnowledgeBaseSettings() {
  const { token } = useAuth();
  const { showError, showSuccess } = useToast();
  const [knowledgeBaseEnabled, setKnowledgeBaseEnabled] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    void loadSettings(token);
  }, [token]);

  async function loadSettings(activeToken: string) {
    try {
      const settings = await apiGet<
        Record<string, unknown>
      >("/api/admin/settings", activeToken);
      setKnowledgeBaseEnabled(Boolean(settings.knowledge_base_enabled));
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to load settings");
    } finally {
      setIsLoading(false);
    }
  }

  async function toggleKnowledgeBase() {
    if (!token || isSaving) return;
    setIsSaving(true);
    try {
      await apiPatch<
        { knowledge_base_enabled: boolean },
        Record<string, unknown>
      >(
        "/api/admin/settings",
        { knowledge_base_enabled: !knowledgeBaseEnabled },
        token,
      );
      setKnowledgeBaseEnabled(!knowledgeBaseEnabled);
      showSuccess(
        knowledgeBaseEnabled
          ? "Knowledge Base disabled."
          : "Knowledge Base enabled.",
      );
    } catch (error) {
      showError(error instanceof Error ? error.message : "Failed to update settings");
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return (
      <section className=" p-5 text-sm text-sand/60">
        Loading...
      </section>
    );
  }

  return (
    <SettingsLayout title="Knowledge Base">
      <article>
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-lg">Knowledge Base</h2>
          <p className="mt-1 max-w-2xl text-sm text-sand/60">
            When enabled, users can access the Knowledge Base at /kb and models with RAG enabled can retrieve relevant documents during chat.
          </p>
        </div>
        <label className="flex items-center gap-3">
          <span className="text-sm text-sand/70">Enable Knowledge Base</span>
          <button
            type="button"
            onClick={toggleKnowledgeBase}
            disabled={isSaving}
            className={`relative inline-flex h-6 w-11 items-center  transition ${knowledgeBaseEnabled ? "bg-sand" : "bg-white/20"} disabled:opacity-50`}
          >
            <span
              className={`inline-block h-4 w-4 transform  bg-white transition ${knowledgeBaseEnabled ? "translate-x-6" : "translate-x-1"}`}
            />
          </button>
        </label>
      </div>
      </article>
    </SettingsLayout>
  );
}
