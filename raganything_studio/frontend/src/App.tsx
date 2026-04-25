import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Code2, Database, GitBranch, MessageSquare, Settings, Zap } from 'lucide-react'
import { ReadinessProvider, useReadiness } from './context/readiness'
import ApiPage from './pages/ApiPage'
import Dashboard from './pages/Dashboard'
import DocumentResultPage from './pages/DocumentResultPage'
import DocumentsPage from './pages/DocumentsPage'
import KnowledgeGraphPage from './pages/KnowledgeGraphPage'
import JobPage from './pages/JobPage'
import QueryPage from './pages/QueryPage'
import SettingsPage from './pages/SettingsPage'
import UploadPage from './pages/UploadPage'

const navItems = [
  { to: '/documents', label: 'Documents', icon: Database },
  { to: '/graph', label: 'Knowledge Graph', icon: GitBranch },
  { to: '/query', label: 'Retrieval', icon: MessageSquare },
  { to: '/api', label: 'API', icon: Code2 },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function ConfigStatusDot() {
  const { fullyConfigured, isLoading } = useReadiness()
  if (isLoading) return null
  return (
    <Link className={`config-dot ${fullyConfigured ? 'config-dot--ok' : 'config-dot--warn'}`} to="/settings">
      {fullyConfigured
        ? <><CheckCircle2 size={13} /> Ready</>
        : <><AlertTriangle size={13} /> Setup required</>}
    </Link>
  )
}

export default function App() {
  return (
    <ReadinessProvider>
      <div className="app-shell">
        <header className="site-header">
          <Link to="/" className="brand">
            <Zap size={18} className="brand-icon" />
            <strong>RAG-Anything</strong>
            <span className="brand-separator">|</span>
            <span className="brand-subtitle">Studio</span>
          </Link>
          <nav className="top-tabs">
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <NavLink key={item.to} to={item.to} end={item.to === '/'}>
                  <Icon size={15} className="top-tab-icon" />
                  {item.label}
                </NavLink>
              )
            })}
          </nav>
          <div className="header-actions">
            <ConfigStatusDot />
            <span className="version-label">v0.1.0/studio</span>
            <Link className="icon-button header-icon" to="/settings" title="Settings">
              <Settings size={16} />
            </Link>
          </div>
        </header>
        <main className="workspace">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/documents/:documentId/result" element={<DocumentResultPage />} />
            <Route path="/documents/new" element={<UploadPage />} />
            <Route path="/graph" element={<KnowledgeGraphPage />} />
            <Route path="/jobs/:jobId" element={<JobPage />} />
            <Route path="/query" element={<QueryPage />} />
            <Route path="/api" element={<ApiPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
        <div className="connection-indicator">
          <span />
          Connected
        </div>
      </div>
    </ReadinessProvider>
  )
}
