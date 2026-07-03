import { useState, useEffect, useCallback, useRef, lazy, Suspense, Component } from 'react'
import { Routes, Route, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Database, Settings, Activity, Zap, Cpu, Hash, Bot, Shield, LogOut, User, Sun, Moon, BookOpen, ChevronDown, Factory, BarChart3, Wrench, GitBranch, ScrollText, AlertTriangle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import { api } from './utils/api'

// ---- Route-level code splitting ----
const KnowledgePage               = lazy(() => import('./pages/KnowledgePage'))
const KnowledgeDetailPage        = lazy(() => import('./pages/KnowledgeDetailPage'))
const SettingsPage                = lazy(() => import('./pages/SettingsPage'))
const MonitorPage                 = lazy(() => import('./pages/MonitorPage'))
const AgentsPage                  = lazy(() => import('./pages/AgentsPage'))
const AgentChatPage               = lazy(() => import('./pages/AgentChatPage'))
const LoginPage                   = lazy(() => import('./pages/LoginPage'))
const RegisterPage                = lazy(() => import('./pages/RegisterPage'))
const AdminUsersPage              = lazy(() => import('./pages/AdminUsersPage'))
const AdminAuditLogsPage          = lazy(() => import('./pages/AdminAuditLogsPage'))
const AutoRepairDashboardPage  = lazy(() => import('./pages/AutoRepairDashboardPage'))
const AutoRepairKnowledgePage  = lazy(() => import('./pages/AutoRepairKnowledgePage'))
const AutoRepairAgentPage      = lazy(() => import('./pages/AutoRepairAgentPage'))
const WorkflowPage                = lazy(() => import('./pages/WorkflowPage'))

// ---- Route-level loading skeleton ----
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <div className="skeleton h-6 w-32" />
  </div>
)

// ---- Error boundary for lazy routes ----
class LazyErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('[LazyErrorBoundary] Route render error:', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <p className="text-ink-muted text-sm">页面加载失败</p>
          {this.state.error && (
            <p className="text-xs text-rose-500 max-w-md text-center font-mono break-all">
              {this.state.error.message || String(this.state.error)}
            </p>
          )}
          <button
            className="btn-secondary text-xs"
            onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload() }}
          >
            重新加载
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// ---- Suspense with timeout: prevents infinite hang on lazy chunk load ----
// Uses an inner LoadDetector component that only renders when Suspense
// resolves, so the timer is cancelled on successful page load.
const SUSPENSE_TIMEOUT_MS = 30000

const ChunkTimeoutFallback = () => (
  <div className="flex flex-col items-center justify-center py-20 gap-3">
    <AlertTriangle size={32} className="text-amber-400" />
    <p className="text-sm font-medium text-ink-body">页面加载超时</p>
    <p className="text-xs text-ink-muted">请检查网络连接后重试</p>
    <button onClick={() => window.location.reload()}
      className="px-4 py-2 text-xs font-medium text-white bg-sky-500 rounded-lg hover:bg-sky-600 transition-colors">
      重新加载
    </button>
  </div>
)

// Renders nothing, but its useEffect fires only after Suspense resolves,
// signalling that lazy chunks have loaded and the timeout can be cancelled.
function LoadDetector({ onLoad }) {
  useEffect(() => { onLoad() }, [onLoad])
  return null
}

function SuspenseWithTimeout({ children, fallback, timeout = SUSPENSE_TIMEOUT_MS }) {
  const [state, setState] = useState('loading') // 'loading' | 'loaded' | 'timeout'
  const markLoaded = useCallback(() => setState('loaded'), [])

  useEffect(() => {
    if (state !== 'loading') return
    const timer = setTimeout(() => setState('timeout'), timeout)
    return () => clearTimeout(timer)
  }, [timeout, state])

  if (state === 'timeout') return <ChunkTimeoutFallback />

  return (
    <Suspense fallback={fallback}>
      <LoadDetector onLoad={markLoaded} />
      {children}
    </Suspense>
  )
}

const NAV = [
  { to: '/knowledge',     icon: Database,   label: '知识库',     requiredPermission: null },
  { to: '/agents',        icon: Bot,       label: '智能体',     requiredPermission: null },
  { to: '/workflow',      icon: GitBranch,  label: '工作流',     requiredPermission: 'workflow:read' },
  { to: '/autorepair', icon: Factory,    label: '汽修智能助手', requiredPermission: 'autorepair:read' },
  { to: '/settings',      icon: Settings,   label: '设置',       requiredPermission: 'settings:read' },
  { to: '/monitor',       icon: Activity,   label: '监控',       requiredPermission: 'monitor:read' },
]

// ---- Role Badge ----
const ROLE_META = {
  super_admin: { label: '超级管理员', color: 'text-rose-500' },
  admin:        { label: '管理员',     color: 'text-rose-500' },  // 向后兼容
  dept_admin:   { label: '系部管理员', color: 'text-amber-600' },
  teacher:      { label: '主讲教师',   color: 'text-sky-600' },
  assistant:    { label: '助理教师',   color: 'text-sage-600' },
  student:      { label: '学生',       color: 'text-ink-muted' },
}

function RoleBadge({ roleName, isAdmin }) {
  const meta = ROLE_META[roleName] || (isAdmin ? ROLE_META.admin : null)
  if (!meta) return <span className="text-ink-muted">普通用户</span>
  return <span className={`font-medium ${meta.color}`}>{meta.label}</span>
}

// ---- User Menu Dropdown ----
function UserMenu({ user, isAdmin, roleName, dark, toggleTheme, onLogout }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!open) return
    const handleEsc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handleEsc)
    return () => document.removeEventListener('keydown', handleEsc)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-cloud-200 transition-colors text-ink-body"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`用户菜单：${user?.username}`}
      >
        <div className="w-6 h-6 rounded-full bg-coral-100 flex items-center justify-center">
          <User size={11} className="text-sky-500" />
        </div>
        <span className="text-xs font-medium max-w-[80px] truncate hidden sm:inline">{user?.username}</span>
        <ChevronDown size={12} className={`text-ink-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full mt-1 w-52 card p-1.5 shadow-cloud-md z-50 origin-top-right"
            role="menu"
          >
            {/* User info */}
            <div className="px-3 py-2.5 border-b border-cloud-200 mb-1">
              <p className="text-sm font-medium text-ink-primary truncate">{user?.username}</p>
              <p className="text-2xs text-ink-muted mt-0.5">
                <RoleBadge roleName={roleName} isAdmin={isAdmin} />
              </p>
            </div>

            {/* Theme toggle */}
            <button
              onClick={() => { toggleTheme(); setOpen(false) }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-ink-body hover:bg-cloud-200 transition-colors"
              role="menuitem"
            >
              {dark ? <Sun size={14} className="text-amber-500" /> : <Moon size={14} className="text-sky-500" />}
              {dark ? '切换到浅色模式' : '切换到深色模式'}
            </button>

            {/* Logout */}
            <button
              onClick={() => { onLogout(); setOpen(false) }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-rose-500 hover:bg-rose-50 transition-colors"
              role="menuitem"
            >
              <LogOut size={14} />
              退出登录
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ---- Main App ----
export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const { token, user, isAdmin, roleName: authRoleName, hasPermission, logout, loading: authLoading } = useAuth()
  const [stats, setStats] = useState({ documents: 0, entities: 0, relations: 0 })
  const [toast, setToast] = useState(null)
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('raganything_theme')
    return saved === 'dark'
  })

  const isAuthPage = location.pathname === '/login' || location.pathname === '/register'

  // Theme
  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('raganything_theme', dark ? 'dark' : 'light')
  }, [dark])

  const toggleTheme = useCallback(() => setDark(d => !d), [])

  // Load global stats
  const loadStats = useCallback(() => {
    api.getStats().then(setStats).catch(err => console.error(err))
  }, [])
  useEffect(() => { if (token) loadStats() }, [location.pathname, token])

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  // 监听全局认证过期事件（api.js 401 触发）
  useEffect(() => {
    const handler = () => {
      // clearAuth 已在 api.js 中通过 removeItem 处理
      // 这里更新 React 状态并跳转登录页
      window.location.reload() // 硬刷新确保所有状态清除
    }
    window.addEventListener('raganything:auth-expired', handler)
    return () => window.removeEventListener('raganything:auth-expired', handler)
  }, [])

  // ---- Loading ----
  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-cloud-100">
        <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="text-center space-y-4">
          <BookOpen size={36} className="mx-auto text-sky-300 animate-float" />
          <p className="text-ink-muted text-sm font-medium">正在准备你的知识空间…</p>
        </motion.div>
      </div>
    )
  }

  // ---- Not logged in ----
  if (!token) {
    return (
      <div className="min-h-screen bg-cloud-100">
        <LazyErrorBoundary>
          <SuspenseWithTimeout fallback={<PageLoader />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="*" element={<LoginPage />} />
            </Routes>
          </SuspenseWithTimeout>
        </LazyErrorBoundary>
      </div>
    )
  }

  // ---- Main Layout ----
  return (
    <div className="min-h-screen bg-cloud-100">
      {/* ========== TOP NAVIGATION BAR ========== */}
      <header className="topnav">
        <div className="topnav-inner">
          {/* Brand */}
          <NavLink to="/knowledge" className="topnav-brand">
            <div className="topnav-brand-icon">
              <BookOpen size={16} className="text-white" />
            </div>
            <span className="topnav-brand-text">
              RAG<span className="text-sky-500">Anything</span>
            </span>
          </NavLink>

          {/* Nav Links */}
          <nav className="topnav-nav">
            {NAV.filter(item => {
              // 权限过滤：检查每个导航项的 requiredPermission
              if (!item.requiredPermission) return true
              return hasPermission(item.requiredPermission)
            }).map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/agents'}
                className={({ isActive }) =>
                  `topnav-link ${isActive ? 'active' : ''}`
                }
              >
                <Icon size={15} />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
            {hasPermission('users:read') && (
              <NavLink
                to="/admin/users"
                className={({ isActive }) =>
                  `topnav-link ${isActive ? 'active' : ''}`
                }
              >
                <Shield size={15} />
                <span className="hidden sm:inline">用户管理</span>
              </NavLink>
            )}
            {hasPermission('audit:read') && (
              <NavLink
                to="/admin/audit-logs"
                className={({ isActive }) =>
                  `topnav-link ${isActive ? 'active' : ''}`
                }
              >
                <ScrollText size={15} />
                <span className="hidden sm:inline">审计日志</span>
              </NavLink>
            )}
          </nav>

          {/* Right side: Stats + User */}
          <div className="topnav-actions">
            {/* Stats inline */}
            <div className="hidden lg:flex items-center gap-3">
              <span className="text-2xs text-ink-muted flex items-center gap-1"><Zap size={10} className="text-sky-400"/>{stats.documents}</span>
              <span className="text-2xs text-ink-muted flex items-center gap-1"><Cpu size={10} className="text-sage-400"/>{stats.entities}</span>
              <span className="text-2xs text-ink-muted flex items-center gap-1"><Hash size={10} className="text-amber-400"/>{stats.relations}</span>
            </div>

            {/* User */}
            <div className="ml-2">
              <UserMenu
                user={user}
                isAdmin={isAdmin}
                roleName={authRoleName}
                dark={dark}
                toggleTheme={toggleTheme}
                onLogout={handleLogout}
              />
            </div>
          </div>
        </div>
      </header>

      {/* ========== MAIN CONTENT ========== */}
      <main className="pt-14">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <LazyErrorBoundary>
            <SuspenseWithTimeout fallback={<PageLoader />}>
              <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25, ease: 'easeOut' }}
              >
                <Routes>
                  <Route path="/" element={<ProtectedRoute><KnowledgePage /></ProtectedRoute>} />
                  <Route path="/agents" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
                  <Route path="/agents/:id" element={<ProtectedRoute><AgentChatPage /></ProtectedRoute>} />
                  <Route path="/knowledge" element={<ProtectedRoute><KnowledgePage /></ProtectedRoute>} />
                  <Route path="/knowledge/:kbName" element={<ProtectedRoute><KnowledgeDetailPage /></ProtectedRoute>} />
                  <Route path="/workflow" element={<ProtectedRoute requiredPermission="workflow:read"><WorkflowPage /></ProtectedRoute>} />
                  <Route path="/autorepair" element={<ProtectedRoute requiredPermission="autorepair:read"><AutoRepairDashboardPage /></ProtectedRoute>} />
                  <Route path="/autorepair/knowledge" element={<ProtectedRoute requiredPermission="autorepair:read"><AutoRepairKnowledgePage /></ProtectedRoute>} />
                  <Route path="/autorepair/agent" element={<ProtectedRoute requiredPermission="autorepair:read"><AutoRepairAgentPage /></ProtectedRoute>} />
                  <Route path="/settings" element={<ProtectedRoute requiredPermission="settings:read"><SettingsPage onToast={showToast} /></ProtectedRoute>} />
                  <Route path="/monitor" element={<ProtectedRoute requiredPermission="monitor:read"><MonitorPage /></ProtectedRoute>} />
                  <Route path="/admin/users" element={<ProtectedRoute requiredPermission="users:read"><AdminUsersPage /></ProtectedRoute>} />
                  <Route path="/admin/audit-logs" element={<ProtectedRoute requiredPermission="audit:read"><AdminAuditLogsPage /></ProtectedRoute>} />
                </Routes>
              </motion.div>
            </AnimatePresence>
            </SuspenseWithTimeout>
          </LazyErrorBoundary>
        </div>
      </main>

      {/* ========== TOAST ========== */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            role="status"
            aria-live="polite"
            className={`fixed bottom-6 right-6 px-5 py-3.5 rounded-2xl text-sm font-medium z-50 shadow-cloud-md backdrop-blur-sm ${
              toast.type === 'error' ? 'toast-error' :
              toast.type === 'success' ? 'toast-success' :
              'toast-info'
            }`}>
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
