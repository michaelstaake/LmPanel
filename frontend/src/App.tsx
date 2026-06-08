import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import ChatPage from "./pages/ChatPage";
import AuthPage from "./pages/AuthPage";
import RegisterPage from "./pages/RegisterPage";
import ApiPage from "./pages/ApiPage";
import ProfilePage from "./pages/ProfilePage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import StatusPage from "./pages/StatusPage";
import DevicesPage from "./pages/DevicesPage";
import ModelsPage from "./pages/ModelsPage";
import NotFoundPage from "./pages/NotFoundPage";
import ForbiddenPage from "./pages/ForbiddenPage";
import KnowledgeBasePage from "./pages/KnowledgeBasePage";
import TermsAcceptancePage from "./pages/TermsAcceptancePage";
import { useAuth } from "./context/AuthContext";
import { MobileNavProvider, type MobileNavSection } from "./context/MobileNavContext";
import { useToast } from "./context/ToastContext";
import { BackgroundProgressProvider } from "./context/BackgroundProgressContext";
import { ModelsCatalogProvider } from "./context/ModelsCatalogContext";
import MobileNavDrawer, { type MobileNavItem } from "./components/ui/MobileNavDrawer";
import ToastViewport from "./components/ui/ToastViewport";
import {
  apiGet,
  BACKEND_UNAVAILABLE_EVENT,
  BACKEND_UNAVAILABLE_MESSAGE,
  isBackendUnavailableLocked,
  resolveApiUrl,
} from "./lib/api";
import { type CurrentUser } from "./lib/session";
import { createFaviconSvg, getSystemStatus } from "./lib/favicon";

const appVersionLabel = `v${__APP_VERSION__}`;
const BACKEND_STATUS_POLL_INTERVAL_MS = 5000;
const MOBILE_BREAKPOINT_PX = 768;

function getMainNavItems(user: CurrentUser | null, knowledgeBaseEnabled: boolean): MobileNavItem[] {
  const items: MobileNavItem[] = [];

  if (user) {
    items.push({ to: "/", end: true, iconClassName: "bi bi-house", label: "Chat" });
    items.push({ to: "/apikeys", iconClassName: "bi bi-key", label: "API" });
    if (knowledgeBaseEnabled && user.is_admin) {
      items.push({ to: "/kb", iconClassName: "bi bi-book-half", label: "KB" });
    }
  }

  if (user?.is_admin) {
    items.push({ to: "/devices", iconClassName: "bi bi-gpu-card", label: "Devices" });
    items.push({ to: "/models", iconClassName: "bi bi-file-earmark", label: "Models" });
    items.push({ to: "/settings", iconClassName: "bi bi-gear", label: "Settings" });
  }

  items.push({ to: "/status", iconClassName: "bi bi-activity", label: "Status" });

  items.push({
    to: user ? "/profile" : "/login",
    iconClassName: "bi bi-person",
    label: user ? user.username : "Login",
  });

  return items;
}

function MainNavLink({
  iconClassName,
  label,
  to,
  end = false,
}: {
  iconClassName: string;
  label: string;
  to: string;
  end?: boolean;
}) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (to === "/" && location.pathname === "/") {
      e.preventDefault();
      navigate("/new-chat");
    }
  };

  return (
    <NavLink
      to={to}
      end={end}
      onClick={handleClick}
      className={({ isActive }) => `inline-flex items-center gap-2 px-3 py-2 text-sm ${isActive ? "bg-sand text-canvas" : "bg-white/10 text-sand hover:bg-white/15"}`}
    >
      <i className={`${iconClassName} text-[14px] leading-none`} aria-hidden="true" />
      <span>{label}</span>
    </NavLink>
  );
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { isBootstrapping, requiresSetup, user } = useAuth();

  if (isBootstrapping) {
    return <section className="p-5 text-sm text-sand/60">Loading...</section>;
  }
  if (requiresSetup) {
    return <Navigate to="/setup" replace />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (!user.is_admin) {
    return <ForbiddenPage />;
  }
  return children;
}

function RequireUser({ children }: { children: ReactNode }) {
  const { isBootstrapping, requiresSetup, user } = useAuth();

  if (isBootstrapping) {
    return <section className="p-5 text-sm text-sand/60">Loading...</section>;
  }
  if (requiresSetup) {
    return <Navigate to="/setup" replace />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function RequireSetup({ children }: { children: ReactNode }) {
  const { isBootstrapping, requiresSetup } = useAuth();

  if (isBootstrapping) {
    return <section className="p-5 text-sm text-sand/60">Loading...</section>;
  }
  if (requiresSetup) {
    return <Navigate to="/setup" replace />;
  }
  return children;
}

function HomeRoute() {
  const { isBootstrapping, requiresSetup, user, termsSettings } = useAuth();

  if (isBootstrapping) {
    return <section className="p-5 text-sm text-sand/60">Loading...</section>;
  }
  if (requiresSetup) {
    return <Navigate to="/setup" replace />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (termsSettings.terms_enabled && !user.terms_accepted) {
    return <Navigate to="/terms" replace />;
  }
  return <ChatPage />;
}

function SetupRoute() {
  const { bootstrapError, isBootstrapping, requiresSetup, user } = useAuth();
  const { showError } = useToast();

  useEffect(() => {
    if (bootstrapError) {
      showError("Unable to check installation state. Confirm the backend is running and reload after resolving the API error.", { id: "setup-bootstrap-error" });
    }
  }, [bootstrapError, showError]);

  if (isBootstrapping) {
    return <section className="p-5 text-sm text-sand/60">Checking installation state...</section>;
  }
  if (bootstrapError) {
    return <section className="p-5 text-sm text-sand/60">Installation state is temporarily unavailable.</section>;
  }
  if (!requiresSetup) {
    return <Navigate to={user ? "/settings/general" : "/login"} replace />;
  }
  return <SetupPage />;
}

export default function App() {
  const { bootstrapError, faviconPath, isBootstrapping, knowledgeBaseEnabled, requiresSetup, user, sitename } = useAuth();
  const { showError } = useToast();
  const location = useLocation();
  const [backendUnavailable, setBackendUnavailable] = useState(() => isBackendUnavailableLocked());
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [mobileNavSection, setMobileNavSection] = useState<MobileNavSection>(null);
  const showMainNav = !isBootstrapping && !requiresSetup;
  const mainNavItems = getMainNavItems(user, knowledgeBaseEnabled);

  const pageTitle = ((): string => {
    const path = location.pathname;
    if (path === "/" || path === "/new-chat" || path === "/chat") return "Chat";
    if (path === "/status") return "Status";
    if (path === "/apikeys" || path === "/api") return "API";
    if (path === "/settings") return "Settings";
   if (path.startsWith("/settings/")) {
      const subPath = path.split("/")[2];
      const labels: Record<string, string> = {
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
      return labels[subPath] || "Settings";
    }
    if (path === "/devices") return "Devices";
    if (path === "/models") return "Models";
    if (path === "/profile") return "Profile";
    if (path === "/login" || path === "/auth") return "Login";
    if (path === "/register") return "Register";
    if (path === "/setup") return "Setup";
    if (path === "/kb") return "Knowledge Base";
    if (path === "/terms") return "Terms and Policies";
    if (path === "/403") return "Forbidden";
    if (path === "/404") return "Not Found";
    return "";
  })();

  useEffect(() => {
    const base = sitename || "LmPanel";
    document.title = pageTitle ? `${pageTitle} ~ ${base}` : base;
  }, [sitename, pageTitle]);

  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');

    function updateFavicon() {
      if (faviconPath) {
        const href = resolveApiUrl(faviconPath);
        if (link) {
          link.href = href;
        } else {
          const newLink = document.createElement("link");
          newLink.rel = "icon";
          newLink.href = href;
          newLink.type = faviconPath.endsWith(".png") ? "image/png" : "image/jpeg";
          document.head.appendChild(newLink);
        }
      } else {
        (async () => {
          const status = await getSystemStatus();
          const href = createFaviconSvg(status);
          if (link) {
            link.href = href;
          } else {
            const newLink = document.createElement("link");
            newLink.rel = "icon";
            newLink.href = href;
            newLink.type = "image/svg+xml";
            document.head.appendChild(newLink);
          }
        })();
      }
    }

    updateFavicon();

    let intervalId: number | undefined;
    if (!faviconPath) {
      intervalId = window.setInterval(updateFavicon, 5000);
    }

    return () => {
      if (intervalId) {
        window.clearInterval(intervalId);
      }
    };
  }, [faviconPath]);

  useEffect(() => {
    function handleBackendUnavailable() {
      setBackendUnavailable(true);
      showError(BACKEND_UNAVAILABLE_MESSAGE, { id: "backend-unavailable" });
    }

    window.addEventListener(BACKEND_UNAVAILABLE_EVENT, handleBackendUnavailable);
    return () => window.removeEventListener(BACKEND_UNAVAILABLE_EVENT, handleBackendUnavailable);
  }, [showError]);

  useEffect(() => {
    if (backendUnavailable) {
      showError(BACKEND_UNAVAILABLE_MESSAGE, { id: "backend-unavailable" });
    }
  }, [backendUnavailable, showError]);

  useEffect(() => {
    if (backendUnavailable) {
      return;
    }

    let isMounted = true;

    async function pollBackendAvailability() {
      try {
        await apiGet("/api/auth/bootstrap-status");
      } catch {
        if (!isMounted) {
          return;
        }
      }
    }

    void pollBackendAvailability();
    const intervalId = window.setInterval(() => {
      void pollBackendAvailability();
    }, BACKEND_STATUS_POLL_INTERVAL_MS);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, [backendUnavailable]);

  useEffect(() => {
    setIsMobileNavOpen(false);
  }, [location.pathname]);

 return (
    <BackgroundProgressProvider>
      <ModelsCatalogProvider>
      <div className="min-h-screen bg-canvas text-sand font-body">
        <ToastViewport />
        <MobileNavProvider value={{ closeMobileNav: () => setIsMobileNavOpen(false), setMobileNavSection }}>
          <div className="mx-auto max-w-7xl px-4 md:px-8">
            <header className="relative z-50 flex items-center justify-between gap-4 overflow-visible py-4 isolate">
              <NavLink to="/" className="inline-flex items-baseline gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sand/30">
                <h1 className="font-display text-2xl font-semibold tracking-tight text-sand">{sitename}</h1>
              </NavLink>
              {showMainNav ? (
                <>
                  <button
                    type="button"
                    onClick={() => setIsMobileNavOpen(true)}
                    className="inline-flex items-center gap-2 border border-white/15 bg-white/10 px-3 py-2 text-sm font-medium text-sand transition hover:bg-white/15 xl:hidden"
                    aria-label="Open navigation menu"
                    aria-expanded={isMobileNavOpen}
                    aria-controls="mobile-nav-title"
                  >
                    <i className="bi bi-list text-[18px] leading-none" aria-hidden="true" />
                    <span>Menu</span>
                  </button>
                  <nav className="hidden items-center gap-2 xl:flex">
                    {mainNavItems.map((item) => (
                      <MainNavLink key={`${item.to}-${item.label}`} to={item.to} end={item.end} iconClassName={item.iconClassName} label={item.label} />
                    ))}
                  </nav>
                </>
              ) : null}
            </header>

            <Routes>
              <Route path="/" element={<HomeRoute />} />
              <Route path="/new-chat" element={<HomeRoute />} />
              <Route path="/settings" element={<RequireAdmin><SettingsPage /></RequireAdmin>} />
              <Route path="/settings/*" element={<RequireAdmin><SettingsPage /></RequireAdmin>} />
              <Route path="/devices" element={<RequireAdmin><DevicesPage /></RequireAdmin>} />
              <Route path="/models" element={<RequireAdmin><ModelsPage /></RequireAdmin>} />
              <Route path="/login" element={<AuthPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/auth" element={<Navigate to="/login" replace />} />
              <Route path="/status" element={<RequireSetup><StatusPage /></RequireSetup>} />
              <Route path="/profile" element={<RequireUser><ProfilePage /></RequireUser>} />
              <Route path="/api" element={<Navigate to="/apikeys" replace />} />
              <Route path="/apikeys" element={<RequireUser><ApiPage /></RequireUser>} />
              <Route path="/kb" element={<RequireAdmin><KnowledgeBasePage /></RequireAdmin>} />
              <Route path="/terms" element={<TermsAcceptancePage />} />
              <Route path="/setup" element={<SetupRoute />} />
              <Route path="/403" element={<ForbiddenPage />} />
              <Route path="/404" element={<NotFoundPage />} />
              <Route path="*" element={requiresSetup ? <Navigate to="/setup" replace /> : <NotFoundPage />} />
            </Routes>

            <MobileNavDrawer
              open={showMainNav && isMobileNavOpen}
              onClose={() => setIsMobileNavOpen(false)}
              sitename={sitename}
              navItems={mainNavItems}
              extraSection={mobileNavSection}
            />
          </div>
        </MobileNavProvider>
      </div>
      </ModelsCatalogProvider>
    </BackgroundProgressProvider>
  );
}
