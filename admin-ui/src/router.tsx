import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '@/contexts/auth-context'
import { useSetupStatus } from '@/hooks/use-admin-api'
import AppShell from '@/components/layout/app-shell'
import LoginPage from '@/pages/login'
import SetupPage from '@/pages/setup'
import DashboardPage from '@/pages/dashboard'
import HealthPage from '@/pages/health'
import SecurityPage from '@/pages/security'
import MonitoringPage from '@/pages/monitoring'
import UsersPage from '@/pages/users'
import ModelsPage from '@/pages/models'
import SettingsPage from '@/pages/settings'
import PluginsPage from '@/pages/plugins'
import PersonaPage from '@/pages/persona'
import ConversationsPage from '@/pages/conversations'
import LogsPage from '@/pages/logs'
import SystemPage from '@/pages/system'
import SkillsPage from '@/pages/skills'
import WorkstreamsPage from '@/pages/workstreams'
import ClusterPage from '@/pages/cluster'
import MemoryPage from '@/pages/memory'

function RequireAuth() {
  const { isAuthenticated } = useAuth()
  const { data: setupStatus, isLoading } = useSetupStatus()

  // Wait for setup status check
  if (isLoading) return null

  // First boot — redirect to setup wizard
  if (setupStatus && !setupStatus.setup_complete) {
    return <Navigate to="/admin/setup" replace />
  }

  if (!isAuthenticated) return <Navigate to="/admin/login" replace />
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}

export default function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/admin/login" element={<LoginPage />} />
        <Route path="/admin/setup" element={<SetupPage />} />
        <Route path="/admin" element={<RequireAuth />}>
          <Route index element={<DashboardPage />} />
          <Route path="health" element={<HealthPage />} />
          <Route path="security" element={<SecurityPage />} />
          <Route path="monitoring" element={<MonitoringPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="plugins" element={<PluginsPage />} />
          <Route path="persona" element={<PersonaPage />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="workstreams" element={<WorkstreamsPage />} />
          <Route path="cluster" element={<ClusterPage />} />
          <Route path="memory" element={<MemoryPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
