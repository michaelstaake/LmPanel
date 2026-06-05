import { useState } from "react";
import ConfigurationPage from "./ConfigurationPage";
import KnowledgeBaseSettings from "./KnowledgeBaseSettings";
import LogsPage from "./LogsPage";
import RunningTasksPage from "./RunningTasksPage";
import UsersPage from "./UsersPage";
import SslPage from "./SslPage";
import WebSearchPage from "./WebSearchPage";
import SecurityPage from "./SecurityPage";
import PackagesPage from "./PackagesPage";
import TermsAndPoliciesPage from "./TermsAndPoliciesPage";

type SettingsTab = "general" | "security" | "packages" | "running_tasks" | "users" | "web_search" | "kb_settings" | "ssl" | "terms" | "logs";

const tabs: { id: SettingsTab; label: string }[] = [
  { id: "general", label: "Configuration" },
  { id: "security", label: "Security" },
  { id: "packages", label: "Packages" },
  { id: "running_tasks", label: "Running Tasks" },
  { id: "users", label: "Users" },
  { id: "web_search", label: "Web Search" },
  { id: "kb_settings", label: "Knowledge Base" },
  { id: "ssl", label: "SSL" },
  { id: "terms", label: "Terms and Policies" },
  { id: "logs", label: "Logs" },
];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  return (
    <div className="grid gap-4">
      <div className="flex gap-1 rounded-2xl border border-black/10 bg-white/80 p-2 shadow-sm backdrop-blur">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${activeTab === tab.id ? "bg-ink text-white" : "text-black/70 hover:bg-black/5"}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "general" && <ConfigurationPage />}
      {activeTab === "security" && <SecurityPage />}
      {activeTab === "packages" && <PackagesPage />}
      {activeTab === "running_tasks" && <RunningTasksPage />}
      {activeTab === "users" && <UsersPage />}
      {activeTab === "web_search" && <WebSearchPage />}
      {activeTab === "kb_settings" && <KnowledgeBaseSettings />}
      {activeTab === "ssl" && <SslPage />}
      {activeTab === "terms" && <TermsAndPoliciesPage />}
      {activeTab === "logs" && <LogsPage />}
    </div>
  );
}
