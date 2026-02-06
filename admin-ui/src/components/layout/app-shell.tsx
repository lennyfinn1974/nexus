import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import Sidebar from './sidebar'

const pageTitles: Record<string, string> = {
  '/admin': 'Dashboard',
  '/admin/health': 'System Health',
  '/admin/security': 'Security',
  '/admin/monitoring': 'Agent Monitoring',
  '/admin/users': 'User Management',
  '/admin/models': 'Models',
  '/admin/settings': 'Settings',
  '/admin/plugins': 'Plugins',
  '/admin/persona': 'Persona',
  '/admin/conversations': 'Conversations',
  '/admin/logs': 'Live Logs',
  '/admin/system': 'System',
  '/admin/skills': 'Skills',
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const title = pageTitles[pathname] || 'Admin'

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-12 flex-shrink-0 items-center border-b border-border px-6">
          <h2 className="text-base font-semibold">{title}</h2>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          {children}
        </div>
      </main>
    </div>
  )
}
