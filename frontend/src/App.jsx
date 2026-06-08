import { useState, useEffect } from 'react'
import { Routes, Route, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Upload, Database, MessageSquare, Settings, Activity, Zap, Cpu, Hash, Layers, Plus, Bot, Trash2, Shield, LogOut, User } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import UploadPage from './pages/UploadPage'
import KnowledgePage from './pages/KnowledgePage'
import QueryPage from './pages/QueryPage'
import SettingsPage from './pages/SettingsPage'
import MonitorPage from './pages/MonitorPage'
import AgentsPage from './pages/AgentsPage'
import AgentChatPage from './pages/AgentChatPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AdminUsersPage from './pages/AdminUsersPage'
import { api, setCurrentKB, getCurrentKB } from './utils/api'

const NAV = [
  { to: '/agents', icon: Bot, label: '智能体' },
  { to: '/knowledge', icon: Database, label: '知识库' },
  { to: '/upload', icon: Upload, label: '上传' },
  { to: '/query', icon: MessageSquare, label: '查询' },
  { to: '/settings', icon: Settings, label: '设置' },
  { to: '/monitor', icon: Activity, label: '监控' },
]

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const { token, user, isAdmin, logout, loading: authLoading } = useAuth()
  const [stats, setStats] = useState({ documents: 0, entities: 0, relations: 0 })
  const [toast, setToast] = useState(null)
  const [kbs, setKBs] = useState([])
  const [activeKB, setActiveKB] = useState('default')
  const [showKBCreator, setShowKBCreator] = useState(false)
  const [newKBName, setNewKBName] = useState('')
  const [showKBDeleteConfirm, setShowKBDeleteConfirm] = useState(null)
  const [deletingKB, setDeletingKB] = useState(false)

  const isAuthPage = location.pathname === '/login' || location.pathname === '/register'

  const loadKBs = () => {
    api.listKBs().then(r => {
      setKBs(r.knowledge_bases || [])
      setActiveKB(r.active)
      setCurrentKB(r.active)
    }).catch(() => {})
    api.getStats().then(setStats).catch(() => {})
  }
  useEffect(() => { if (token) loadKBs() }, [location.pathname, token])

  const switchKB = async (name) => {
    await api.switchKB(name)
    setCurrentKB(name)
    setActiveKB(name)
    loadKBs()
  }

  const createKB = async () => {
    if (!newKBName.trim()) return
    await api.createKB(newKBName, newKBName)
    setNewKBName('')
    setShowKBCreator(false)
    loadKBs()
  }

  const deleteKB = async (name) => {
    setDeletingKB(true)
    try {
      await api.deleteKB(name)
      setShowKBDeleteConfirm(null)
      loadKBs()
      showToast(`知识库 "${name}" 已删除`, 'success')
    } catch (e) {
      showToast('删除失败: ' + e.message, 'error')
    } finally {
      setDeletingKB(false)
    }
  }

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  // Loading state
  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-950">
        <div className="text-neon-400 text-sm animate-pulse">加载中…</div>
      </div>
    )
  }

  // Not logged in — show auth pages only
  if (!token) {
    return (
      <div className="min-h-screen bg-slate-950">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 glass m-3 mr-0 flex flex-col shrink-0">
        <div className="p-5 border-b border-slate-700/50">
          <h1 className="font-display font-bold text-lg tracking-tight">
            <span className="text-neon-400">RAG</span>
            <span className="text-slate-300">Anything</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 font-mono">v1.4.0</p>
        </div>

        {/* User Info */}
        <div className="px-3 py-2 border-b border-slate-700/50">
          <div className="flex items-center gap-2 text-xs">
            <div className="w-6 h-6 rounded-full bg-neon-500/20 flex items-center justify-center">
              <User size={12} className="text-neon-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-slate-300 truncate">{user?.username}</p>
              <p className="text-[10px] text-slate-500">
                {isAdmin ? <span className="text-amber-400">管理员</span> : '用户'}
              </p>
            </div>
            <button onClick={handleLogout} className="text-slate-500 hover:text-red-400" title="登出">
              <LogOut size={14} />
            </button>
          </div>
        </div>

        <nav className="p-3 space-y-1">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'bg-neon-500/10 text-neon-400 border border-neon-500/20'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
          {/* Admin Nav */}
          {isAdmin && (
            <NavLink
              to="/admin/users"
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`
              }
            >
              <Shield size={18} />
              用户管理
            </NavLink>
          )}
        </nav>

        {/* KB Selector */}
        <div className="px-3 pb-2 border-t border-slate-700/50 pt-3 mt-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1"><Layers size={10}/>知识库</span>
            <div className="flex items-center gap-1">
              <button className="text-slate-500 hover:text-neon-400" onClick={() => setShowKBCreator(!showKBCreator)} title="新建知识库">
                <Plus size={14}/>
              </button>
              {activeKB !== 'default' && (
                <button className="text-slate-500 hover:text-red-400" onClick={() => setShowKBDeleteConfirm(activeKB)} title="删除知识库">
                  <Trash2 size={13}/>
                </button>
              )}
            </div>
          </div>
          <select className="input-field text-xs py-1.5 w-full" value={activeKB}
            onChange={e => switchKB(e.target.value)}>
            {kbs.map(kb => <option key={kb.name} value={kb.name}>{kb.label}</option>)}
          </select>
          {showKBCreator && (
            <div className="mt-2 flex gap-1">
              <input className="input-field text-xs py-1 flex-1" placeholder="知识库名称" value={newKBName}
                onChange={e => setNewKBName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createKB()} />
              <button className="btn-primary text-xs py-1 px-2" onClick={createKB}>创建</button>
            </div>
          )}
          {showKBDeleteConfirm && (
            <div className="mt-2 p-2 rounded-lg bg-red-500/10 border border-red-500/20">
              <p className="text-xs text-slate-300 mb-1">删除知识库 "<span className="text-red-400">{showKBDeleteConfirm}</span>"？</p>
              <p className="text-[10px] text-amber-400 mb-2">将清除所有文档、实体和向量数据，不可恢复</p>
              <div className="flex gap-1">
                <button className="flex-1 py-1 rounded text-[10px] bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50"
                  disabled={deletingKB}
                  onClick={() => deleteKB(showKBDeleteConfirm)}>
                  {deletingKB ? '删除中…' : '确认删除'}
                </button>
                <button className="flex-1 py-1 rounded text-[10px] bg-slate-700 text-slate-400 hover:bg-slate-600"
                  onClick={() => setShowKBDeleteConfirm(null)}>
                  取消
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-slate-700/50 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span className="flex items-center gap-1.5"><Zap size={12} className="text-neon-400"/>文档</span>
            <span className="font-mono text-slate-300">{stats.documents}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span className="flex items-center gap-1.5"><Cpu size={12} className="text-emerald-400"/>实体</span>
            <span className="font-mono text-slate-300">{stats.entities}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span className="flex items-center gap-1.5"><Hash size={12} className="text-amber-400"/>关系</span>
            <span className="font-mono text-slate-300">{stats.relations}</span>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto m-3 ml-0">
        <div className="glass min-h-full p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={`${location.pathname}-${activeKB}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
            >
              <Routes>
                {/* Public routes (no auth needed after login) */}
                <Route path="/" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
                <Route path="/agents" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
                <Route path="/agents/:id" element={<ProtectedRoute><AgentChatPage /></ProtectedRoute>} />
                <Route path="/upload" element={<ProtectedRoute><UploadPage onToast={showToast} /></ProtectedRoute>} />
                <Route path="/knowledge" element={<ProtectedRoute><KnowledgePage /></ProtectedRoute>} />
                <Route path="/query" element={<ProtectedRoute><QueryPage /></ProtectedRoute>} />
                <Route path="/settings" element={<ProtectedRoute><SettingsPage onToast={showToast} /></ProtectedRoute>} />
                <Route path="/monitor" element={<ProtectedRoute><MonitorPage /></ProtectedRoute>} />
                {/* Admin routes */}
                <Route path="/admin/users" element={<ProtectedRoute adminOnly><AdminUsersPage /></ProtectedRoute>} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 px-5 py-3 rounded-lg text-sm font-medium z-50 animate-fade-in ${
          toast.type === 'error' ? 'bg-red-500/20 text-red-300 border border-red-500/30' :
          toast.type === 'success' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
          'bg-neon-500/20 text-neon-300 border border-neon-500/30'
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
