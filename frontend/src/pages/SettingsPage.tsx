import { Route, Routes } from "react-router-dom";
import ConfigurationPage from "./ConfigurationPage";
import SecurityPage from "./SecurityPage";
import PackagesPage from "./PackagesPage";
import RunningTasksPage from "./RunningTasksPage";
import UsersPage from "./UsersPage";
import WebSearchPage from "./WebSearchPage";
import KnowledgeBaseSettings from "./KnowledgeBaseSettings";
import SslPage from "./SslPage";
import TermsAndPoliciesPage from "./TermsAndPoliciesPage";
import LogsPage from "./LogsPage";
import SettingsHomePage from "./SettingsHomePage";
import NotificationSettingsPage from "./NotificationSettingsPage";
import MailSettingsPage from "./MailSettingsPage";

export default function SettingsPage() {
  return (
    <Routes>
      <Route index element={<SettingsHomePage />} />
      <Route path="general" element={<ConfigurationPage />} />
      <Route path="security" element={<SecurityPage />} />
      <Route path="packages" element={<PackagesPage />} />
      <Route path="running_tasks" element={<RunningTasksPage />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="web_search" element={<WebSearchPage />} />
      <Route path="kb_settings" element={<KnowledgeBaseSettings />} />
      <Route path="ssl" element={<SslPage />} />
      <Route path="terms" element={<TermsAndPoliciesPage />} />
      <Route path="logs" element={<LogsPage />} />
      <Route path="notifications" element={<NotificationSettingsPage />} />
      <Route path="mail" element={<MailSettingsPage />} />
      <Route path="*" element={<SettingsHomePage />} />
    </Routes>
  );
}
