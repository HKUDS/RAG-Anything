import { useState, useEffect, useCallback, useRef } from 'react'
import { Routes, Route, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Database, Settings, Activity, Zap, Cpu, Hash, Bot, Shield, LogOut, User, Sun, Moon, BookOpen, ChevronDown, Factory, BarChart3, Wrench, GitBranch, ScrollText } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import KnowledgePage from './pages/KnowledgePage'

import SettingsPage from './pages/SettingsPage'
import MonitorPage from './pages/MonitorPage'
import AgentsPage from './pages/AgentsPage'
import AgentChatPage from './pages/AgentChatPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AdminUsersPage from './pages/AdminUsersPage'
import AdminAuditLogsPage from './pages/AdminAuditLogsPage'
import ManufacturingDashboardPage from './pages/ManufacturingDashboardPage'
import ManufacturingKnowledgePage from './pages/ManufacturingKnowledgePage'
import ManufacturingAgentPage from './pages/ManufacturingAgentPage'
import WorkflowPage from './pages/WorkflowPage'
import { api } from './utils/api'

const NAV = [
  { to: '/agents',    icon: Bot,           label: '智能体' },
  { to: '/knowledge', icon: Database,       label: '知识库' },

  { to: '/workflow',  icon: GitBranch,      label: '工作流' },
  { to: '/manufacturing', icon: Factory,    label: '制造智能体' },
  { to: '/settings',  icon: Settings,       label: '设置' },
  { to: '/monitor',   icon: Activity,       label: '监控' },
]

// ---- User Menu Dropdown ----
function UserMenu({ user, isAdmin, dark, toggleTheme, onLogout }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-warm-100 transition-colors text-warm-600"
      >
        <div className="w-6 h-6 rounded-full bg-coral-100 flex items-center justify-center">
          <User size={11} className="text-coral-500" />
        </div>
        <span className="text-xs font-medium max-w-[80px] truncate hidden sm:inline">{user?.username}</span>
        <ChevronDown size={12} className={`text-warm-500 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full mt-1 w-52 card p-1.5 shadow-warm-md z-50 origin-top-right"
          >
            {/* User info */}
            <div className="px-3 py-2.5 border-b border-warm-100 mb-1">
              <p className="text-sm font-medium text-warm-800 truncate">{user?.username}</p>
              <p className="text-2xs text-warm-500 mt-0.5">
                {isAdmin ? <span className="text-amber-600 font-medium">管理员</span> : '普通用户'}
              </p>
            </div>

            {/* Theme toggle */}
            <button
              onClick={() => { toggleTheme(); setOpen(false) }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-warm-600 hover:bg-warm-50 transition-colors"
            >
              {dark ? <Sun size={14} className="text-amber-500" /> : <Moon size={14} className="text-sky-500" />}
              {dark ? '切换到浅色模式' : '切换到深色模式'}
            </button>

            {/* Logout */}
            <button
              onClick={() => { onLogout(); setOpen(false) }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-rose-500 hover:bg-rose-50 transition-colors"
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
  const { token, user, isAdmin, logout, loading: authLoading } = useAuth()
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
    api.getStats().then(setStats).catch(() => {})
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
      <div className="flex items-center justify-center h-screen bg-warm-100">
        <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="text-center space-y-4">
          <BookOpen size={36} className="mx-auto text-warm-400 animate-float" />
          <p className="text-warm-500 text-sm font-medium">正在准备你的知识空间…</p>
        </motion.div>
      </div>
    )
  }

  // ---- Not logged in ----
  if (!token) {
    return (
      <div className="min-h-screen bg-warm-100">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </div>
    )
  }

  // ---- Main Layout ----
  return (
    <div className="min-h-screen bg-warm-100">
      {/* ========== TOP NAVIGATION BAR ========== */}
      <header className="topnav">
        <div className="topnav-inner">
          {/* Brand */}
          <NavLink to="/agents" className="topnav-brand">
            <div className="topnav-brand-icon">
              <BookOpen size={16} className="text-white" />
            </div>
            <span className="topnav-brand-text">
              RAG<span className="text-coral-500">Anything</span>
            </span>
          </NavLink>

          {/* Nav Links */}
          <nav className="topnav-nav">
            {NAV.map(({ to, icon: Icon, label }) => (
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
            {isAdmin && (
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
            {isAdmin && (
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
              <span className="text-2xs text-warm-500 flex items-center gap-1"><Zap size={10} className="text-coral-400"/>{stats.documents}</span>
              <span className="text-2xs text-warm-500 flex items-center gap-1"><Cpu size={10} className="text-sage-400"/>{stats.entities}</span>
              <span className="text-2xs text-warm-500 flex items-center gap-1"><Hash size={10} className="text-amber-400"/>{stats.relations}</span>
            </div>

            {/* User */}
            <div className="ml-2">
              <UserMenu
                user={user}
                isAdmin={isAdmin}
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
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.25, ease: 'easeOut' }}
            >
              <Routes>
                <Route path="/" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
                <Route path="/agents" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
                <Route path="/agents/:id" element={<ProtectedRoute><AgentChatPage /></ProtectedRoute>} />
                <Route path="/knowledge" element={<ProtectedRoute><KnowledgePage /></ProtectedRoute>} />

                <Route path="/settings" element={<ProtectedRoute><SettingsPage onToast={showToast} /></ProtectedRoute>} />
                <Route path="/monitor" element={<ProtectedRoute><MonitorPage /></ProtectedRoute>} />
                <Route path="/admin/users" element={<ProtectedRoute adminOnly><AdminUsersPage /></ProtectedRoute>} />
                <Route path="/admin/audit-logs" element={<ProtectedRoute adminOnly><AdminAuditLogsPage /></ProtectedRoute>} />
                <Route path="/manufacturing" element={<ProtectedRoute><ManufacturingDashboardPage /></ProtectedRoute>} />
                <Route path="/manufacturing/knowledge" element={<ProtectedRoute><ManufacturingKnowledgePage /></ProtectedRoute>} />
                <Route path="/manufacturing/agent" element={<ProtectedRoute><ManufacturingAgentPage /></ProtectedRoute>} />
                <Route path="/workflow" element={<ProtectedRoute><WorkflowPage /></ProtectedRoute>} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      {/* ========== TOAST ========== */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            className={`fixed bottom-6 right-6 px-5 py-3.5 rounded-2xl text-sm font-medium z-50 shadow-warm-md backdrop-blur-sm ${
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
