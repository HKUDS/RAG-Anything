import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { Activity, AlertTriangle, CheckCircle2, Database, FilePlus2, MessageSquare, Settings } from 'lucide-react'
import { ReadinessProvider, useReadiness } from './context/readiness'
import Dashboard from './pages/Dashboard'
import DocumentsPage from './pages/DocumentsPage'
import JobPage from './pages/JobPage'
import QueryPage from './pages/QueryPage'
import SettingsPage from './pages/SettingsPage'
import UploadPage from './pages/UploadPage'

const navItems = [
  { to: '/', label: 'Dashboard', icon: Activity },
  { to: '/documents', label: 'Documents', icon: Database },
  { to: '/documents/new', label: 'Upload', icon: FilePlus2 },
  { to: '/query', label: 'Query', icon: MessageSquare },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function ConfigStatusDot() {
  const { fullyConfigured, isLoading } = useReadiness()
  if (isLoading) return null
  return (
    <div className={`config-dot ${fullyConfigured ? 'config-dot--ok' : 'config-dot--warn'}`}>
      {fullyConfigured
        ? <><CheckCircle2 size={13} /> Ready</>
        : <><AlertTriangle size={13} /> Setup required</>}
    </div>
  )
}

export default function App() {
  return (
    <ReadinessProvider>
      <div className="app-shell">
        <aside className="sidebar">
          <Link to="/" className="brand">
            <span className="brand-mark">RA</span>
            <span>
              <strong>RAG-Anything</strong>
              <small>Studio</small>
            </span>
          </Link>
          <nav>
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <NavLink key={item.to} to={item.to} end={item.to === '/'}>
                  <Icon size={18} />
                  {item.label}
                </NavLink>
              )
            })}
          </nav>
          <div className="sidebar-footer">
            <ConfigStatusDot />
          </div>
        </aside>
        <main className="workspace">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/documents/new" element={<UploadPage />} />
            <Route path="/jobs/:jobId" element={<JobPage />} />
            <Route path="/query" element={<QueryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </ReadinessProvider>
  )
}
