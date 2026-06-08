import { NavLink } from "react-router-dom";
import SettingsLayout from "./SettingsLayout";

type SettingsNavItem = {
  id: string;
  label: string;
  iconClassName: string;
  description: string;
};

const settingsNavItems: SettingsNavItem[] = [
  { id: "general", label: "Configuration", iconClassName: "bi bi-gear", description: "Site name, URL, favicon, and registration" },
  { id: "security", label: "Security", iconClassName: "bi bi-shield-lock", description: "CAPTCHA, 2FA, and authentication" },
  { id: "users", label: "Users", iconClassName: "bi bi-people", description: "Manage user accounts and permissions" },
  { id: "packages", label: "Packages", iconClassName: "bi bi-box", description: "Token and tool usage limits" },
  { id: "running_tasks", label: "Running Tasks", iconClassName: "bi bi-activity", description: "Monitor active tasks and processes" },
  { id: "web_search", label: "Web Search", iconClassName: "bi bi-globe", description: "Configure web search settings" },
  { id: "kb_settings", label: "Knowledge Base", iconClassName: "bi bi-book-half", description: "Knowledge base and RAG settings" },
  { id: "ssl", label: "SSL", iconClassName: "bi bi-lock", description: "SSL/TLS certificate management" },
  { id: "terms", label: "Terms and Policies", iconClassName: "bi bi-file-text", description: "Terms of service and policies" },
  { id: "logs", label: "Logs", iconClassName: "bi bi-journal-text", description: "Application logs and audit trail" },
  { id: "updates", label: "Updates", iconClassName: "bi bi-arrow-down-circle", description: "Check for and manage updates" },
  { id: "notifications", label: "Notifications", iconClassName: "bi bi-bell", description: "Alert types and notification preferences" },
  { id: "mail", label: "Mail", iconClassName: "bi bi-envelope", description: "Email server configuration" },
];

export default function SettingsHomePage() {
  return (
    <SettingsLayout>
      <div className="surface-muted mb-4 px-4 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-display text-xl">LmPanel</h2>
            <p className="mt-1 text-sm text-sand/60">
              v{__APP_VERSION__}
              {__APP_GIT_COMMIT__ ? `.${__APP_GIT_COMMIT__}` : ""}
            </p>
          </div>
          <a
            href="https://github.com/michaelstaake/LmPanel"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-semibold text-sand underline underline-offset-2 hover:text-sand/80"
          >
            GitHub
          </a>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {settingsNavItems.map((item) => (
          <NavLink
            key={item.id}
            to={item.id}
            className={({ isActive }) =>
              `group surface-muted p-5 transition hover:border-white/20 hover:bg-white/10 ${isActive ? "border-white/25 bg-white/10" : ""}`
            }
          >
            <div className="flex items-start gap-4">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center  text-lg ${
                "bg-white/10 text-sand/70 group-hover:bg-white/15"
              }`}>
                <i className={item.iconClassName} aria-hidden="true" />
              </div>
              <div>
                <div className="text-sm font-semibold text-sand">{item.label}</div>
                <p className="mt-1 text-xs text-sand/55">{item.description}</p>
              </div>
            </div>
          </NavLink>
        ))}
      </div>
    </SettingsLayout>
  );
}
