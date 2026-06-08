import { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

type SettingsLayoutProps = {
  children: ReactNode;
  title?: string;
};

const settingsRouteLabels: Record<string, string> = {
  general: "Configuration",
  security: "Security",
  users: "Users",
  packages: "Packages",
  running_tasks: "Running Tasks",
  web_search: "Web Search",
  kb_settings: "Knowledge Base",
  ssl: "SSL",
  terms: "Terms and Policies",
  logs: "Logs",
  updates: "Updates",
  notifications: "Notifications",
  mail: "Mail",
};

export default function SettingsLayout({ children, title }: SettingsLayoutProps) {
  const location = useLocation();

  const breadcrumbs = ((): { label: string; to: string }[] => {
    const items: { label: string; to: string }[] = [{ label: "Settings", to: "/settings" }];

    if (title) {
      items.push({ label: title, to: location.pathname });
    } else {
      const pathParts = location.pathname.split("/").filter(Boolean);
      for (const part of pathParts) {
        const label = settingsRouteLabels[part] || part;
        items.push({ label, to: `/settings/${part}` });
      }
    }

    return items;
  })();

  const showBreadcrumbs = title && breadcrumbs.length > 1;

  return (
    <div className="py-5">
      {showBreadcrumbs && (
        <nav aria-label="Breadcrumb" className="mb-4 text-sm">
          <ol className="flex items-center gap-1.5">
            {breadcrumbs.map((crumb, index) => (
              <li key={crumb.to} className="flex items-center gap-1.5">
                {index > 0 && <span className="text-sand/40" aria-hidden="true">/</span>}
                {index === breadcrumbs.length - 1 ? (
                  <span className="font-semibold text-sand">{crumb.label}</span>
                ) : (
                  <Link to={crumb.to} className="text-sand/70 hover:text-white">
                    {crumb.label}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      <div className="surface grid gap-4 p-5">
        {children}
      </div>
    </div>
  );
}
