import { NavLink } from 'react-router-dom'
import { useAuth } from '@/contexts/auth-context'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard, Heart, Shield, Activity, Users, Layers, Settings,
  Puzzle, UserCircle, MessageSquare, ScrollText, Monitor, Zap, LogOut, ArrowLeft, Kanban, Network, Brain,
} from 'lucide-react'

const navSections = [
  {
    label: 'Overview',
    items: [
      { to: '/admin', icon: LayoutDashboard, label: 'Dashboard', end: true },
      { to: '/admin/health', icon: Heart, label: 'System Health' },
    ],
  },
  {
    label: 'Security',
    items: [
      { to: '/admin/security', icon: Shield, label: 'Security' },
      { to: '/admin/monitoring', icon: Activity, label: 'Monitoring' },
      { to: '/admin/users', icon: Users, label: 'Users' },
    ],
  },
  {
    label: 'Configure',
    items: [
      { to: '/admin/models', icon: Layers, label: 'Models' },
      { to: '/admin/settings', icon: Settings, label: 'Settings' },
      { to: '/admin/plugins', icon: Puzzle, label: 'Plugins' },
      { to: '/admin/persona', icon: UserCircle, label: 'Persona' },
      { to: '/admin/skills', icon: Zap, label: 'Skills' },
    ],
  },
  {
    label: 'Monitor',
    items: [
      { to: '/admin/cluster', icon: Network, label: 'Cluster' },
      { to: '/admin/memory', icon: Brain, label: 'Memory' },
      { to: '/admin/workstreams', icon: Kanban, label: 'Work Streams' },
      { to: '/admin/conversations', icon: MessageSquare, label: 'Conversations' },
      { to: '/admin/logs', icon: ScrollText, label: 'Logs' },
      { to: '/admin/system', icon: Monitor, label: 'System' },
    ],
  },
]

export default function Sidebar() {
  const { logout } = useAuth()

  return (
    <aside className="flex h-screen w-[220px] flex-shrink-0 flex-col border-r border-border bg-sidebar-background">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-purple-400 text-sm font-bold text-white">
          N
        </div>
        <div>
          <h1 className="text-sm font-bold text-foreground">Nexus</h1>
          <span className="font-mono text-[10px] text-muted-foreground">v2.0 Admin</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-2">
        {navSections.map((section) => (
          <div key={section.label}>
            <div className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {section.label}
            </div>
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    'mb-0.5 flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors',
                    isActive
                      ? 'bg-primary/15 text-primary'
                      : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                  )
                }
              >
                <item.icon className="h-4 w-4 flex-shrink-0" />
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-border p-3 space-y-1">
        <a
          href="/"
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-primary transition-colors"
        >
          <ArrowLeft className="h-3 w-3" /> Back to Chat
        </a>
        <button
          onClick={logout}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-destructive transition-colors"
        >
          <LogOut className="h-3 w-3" /> Sign Out
        </button>
      </div>
    </aside>
  )
}
