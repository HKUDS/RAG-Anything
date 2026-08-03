import { useState, useEffect, useCallback, useRef, lazy, Suspense, Component } from 'react'
import { Routes, Route, NavLink, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Database, Settings, Activity, Zap, Cpu, Hash, Bot, Shield, LogOut, User, Sun, Moon, BookOpen, ChevronDown, Factory, GitBranch, ScrollText, AlertTriangle } from 'lucide-react'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import { api } from './utils/api'
import { settingsRedirectDestination } from './utils/settingsRouting'
import { createPermissionUiPolicy } from './utils/permissionUiPolicy'

// ---- 路由级代码拆分 ----
const KnowledgePage               = lazy(() => import('./pages/KnowledgePage'))
const KnowledgeDetailPage        = lazy(() => import('./pages/KnowledgeDetailPage'))
const DocumentChunksPage         = lazy(() => import('./pages/DocumentChunksPage'))
const DocumentChunkDetailPage    = lazy(() => import('./pages/DocumentChunkDetailPage'))
const PreferencesPage             = lazy(() => import('./pages/PreferencesPage'))
const AdminPlatformPage           = lazy(() => import('./pages/AdminPlatformPage'))
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

// 导航 hover 预取：与 lazy() 使用相同的动态 import（模块缓存去重），
// 仅在可见且有权限的导航项上触发，并遵守 saveData 节能约定。
const ROUTE_PREFETCH = {
  '/knowledge': () => import('./pages/KnowledgePage'),
  '/agents': () => import('./pages/AgentsPage'),
  '/workflow': () => import('./pages/WorkflowPage'),
  '/autorepair': () => import('./pages/AutoRepairDashboardPage'),
  '/monitor': () => import('./pages/MonitorPage'),
  '/admin/platform': () => import('./pages/AdminPlatformPage'),
  '/preferences': () => import('./pages/PreferencesPage'),
  '/admin/users': () => import('./pages/AdminUsersPage'),
  '/admin/audit-logs': () => import('./pages/AdminAuditLogsPage'),
}

// ---- 路由级加载骨架 ----
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <div className="skeleton h-6 w-32" />
  </div>
)

// One-release compatibility route: platform readers retain their management
// destination while every other authenticated user lands in personal settings.
function SettingsRedirect() {
  const { hasPermission } = useAuth()
  return <Navigate replace to={settingsRedirectDestination(hasPermission('settings:read'))} />
}

// ---- 懒加载路由错误边界 ----
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

// ---- 带超时的 Suspense，避免懒加载分块无限等待 ----
// 使用内部 LoadDetector 组件，它只会在 Suspense
// 完成后渲染，因此页面成功加载时会取消计时器。
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

// 该组件不渲染内容，但 useEffect 只会在 Suspense 完成后触发，
// 用于标记懒加载分块已完成并取消超时。
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
  { to: '/knowledge', icon: Database, label: '知识库', requiredPermission: 'kb:read' },
  { to: '/agents', icon: Bot, label: '智能体', requiredPermission: 'agent:read' },
  { to: '/workflow', icon: GitBranch, label: '工作流', requiredPermission: 'workflow:read' },
  { to: '/autorepair', icon: Factory, label: '汽修智能助手', requiredPermission: 'autorepair:read' },
  { to: '/preferences', icon: Settings, label: '个人设置', requiredPermission: null },
  { to: '/monitor', icon: Activity, label: '监控', requiredPermission: 'monitor:read' },
]

const NAV_ITEMS = [
  { to: '/knowledge', icon: Database, label: '知识库', desc: '浏览文档 / 实体 / 图谱', requiredPermission: 'kb:read' },
  { to: '/agents', icon: Bot, label: '智能体', desc: '使用教学问答与推理', requiredPermission: 'agent:read' },
  { to: '/workflow', icon: GitBranch, label: '工作流', desc: '查看知识处理链路', requiredPermission: 'workflow:read' },
  { to: '/autorepair', icon: Factory, label: '汽修智能助手', desc: '查看专业场景工作台', requiredPermission: 'autorepair:read' },
  { to: '/monitor', icon: Activity, label: '监控', desc: '服务状态与指标', requiredPermission: 'monitor:read' },
  { to: '/admin/platform', icon: Settings, label: '平台管理', desc: '默认值与资源上限', requiredPermission: 'settings:read' },
  { to: '/admin/users', icon: Shield, label: '用户管理', desc: '角色与权限', requiredPermission: 'users:read' },
  { to: '/admin/audit-logs', icon: ScrollText, label: '审计日志', desc: '操作追踪', requiredPermission: 'audit:read' },
  { to: '/preferences', icon: Settings, label: '个人设置', desc: '模型、检索与账户', requiredPermission: null },
]

const ROUTE_META = [
  { test: p => /^\/knowledge\/[^/]+\/documents\/[^/]+\/chunks\/[^/]+\/?$/.test(p), kicker: '知识资产', title: '切块详情', subtitle: '阅读、核对并维护一个可检索切块。' },
  { test: p => /^\/knowledge\/[^/]+\/documents\/[^/]+\/chunks\/?$/.test(p), kicker: '知识资产', title: '切块详情', subtitle: '检索、核对并维护文档的检索切块。' },
  { test: p => p.startsWith('/knowledge/'), kicker: '知识资产', title: '知识资产视图', subtitle: '查看文档、分块、实体关系与知识图谱结构。' },
  { test: p => p.startsWith('/knowledge'), kicker: '知识核心', title: '知识库中枢', subtitle: '组织多源文档、实体网络和可检索的知识空间。' },
  { test: p => p.startsWith('/agents/'), kicker: '智能体会话', title: '智能体对话', subtitle: '基于知识库进行检索增强问答、多模态理解与推理。' },
  { test: p => p.startsWith('/agents'), kicker: '智能体矩阵', title: '智能体矩阵', subtitle: '配置模型、检索模式和专业提示词，构建任务型助手。' },
  { test: p => p.startsWith('/workflow'), kicker: '工作流引擎', title: '工作流编排', subtitle: '用节点化流程组织文档处理、检索和推理链路。' },
  { test: p => p.startsWith('/autorepair'), kicker: '场景实验室', title: '汽修智能制造工作台', subtitle: '面向专业教学与竞赛场景的知识图谱和智能问答系统。' },
  { test: p => p.startsWith('/monitor'), kicker: '运行管理', title: '运行监控', subtitle: '观察服务状态、处理吞吐和知识系统运行指标。' },
  { test: p => p.startsWith('/admin/platform'), kicker: '系统配置', title: '平台管理', subtitle: '维护默认值、允许范围和资源硬上限。' },
  { test: p => p.startsWith('/preferences'), kicker: '账户中心', title: '个人设置', subtitle: '管理模型、检索、解析、外观与账户安全。' },
  { test: p => p.startsWith('/admin/users'), kicker: '管理后台', title: '用户与权限', subtitle: '管理账号、角色、部门和访问边界。' },
  { test: p => p.startsWith('/admin/audit-logs'), kicker: '管理后台', title: '审计日志', subtitle: '追踪关键操作与安全事件。' },
]

const getRouteMeta = (pathname, policy = {}) => {
  const route = ROUTE_META.find(item => item.test(pathname))
  if (route) {
    if (pathname.startsWith('/agents') && !pathname.startsWith('/agents/')) {
      return { ...route, subtitle: policy.canWriteAgents ? '配置模型、检索模式和专业提示词，构建任务型助手。' : '浏览可用智能体并进入授权的教学问答。' }
    }
    if (pathname.startsWith('/knowledge')) {
      if (policy.canWriteKnowledge) return route
      const isChunkRoute = pathname.includes('/chunks')
      return { ...route, subtitle: isChunkRoute ? '查看文档的检索切块与内容。' : '查看文档、实体关系与知识图谱结构。' }
    }
    if (pathname.startsWith('/workflow')) {
      return { ...route, subtitle: policy.canWriteWorkflow ? '用节点化流程组织文档处理、检索和推理链路。' : '查看已授权的节点化流程和处理链路。' }
    }
    if (pathname.startsWith('/autorepair')) {
      return { ...route, subtitle: policy.canWriteAutoRepair ? '面向专业教学与竞赛场景的知识图谱和智能问答系统。' : '查看专业教学场景的知识图谱和可用内容。' }
    }
    if (pathname.startsWith('/admin/platform')) {
      return { ...route, subtitle: policy.canWriteSettings ? '维护默认值、允许范围和资源硬上限。' : '查看平台默认值、允许范围和资源上限。' }
    }
    return route
  }
  return {
    kicker: '知元平台',
    title: '多模态教学知识服务平台',
    subtitle: '以课程资源、知识库、智能体和工作流连接教学内容与学习服务。',
  }
}

const formatStatValue = (value) => {
  const n = Number(value || 0)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '0'
}

const getCockpitStats = (pathname, stats, hasPermission, policy = {}) => {
  if (pathname === '/' || pathname.startsWith('/knowledge')) {
    return [
      { label: '文档', value: formatStatValue(stats.documents), icon: Zap, tone: 'blue' },
      { label: '实体', value: formatStatValue(stats.entities), icon: Cpu, tone: 'green' },
      { label: '关系', value: formatStatValue(stats.relations), icon: Hash, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/agents/')) {
    return [
      { label: '助手', value: '会话中', icon: Bot, tone: 'blue' },
      { label: '检索', value: '增强', icon: Database, tone: 'green' },
      { label: '回答', value: '在线', icon: Zap, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/agents')) {
    return [
      { label: '助手', value: policy.canWriteAgents ? '可配置' : '可使用', icon: Bot, tone: 'blue' },
      { label: '知识库', value: policy.canWriteAgents ? '可绑定' : '可查看', icon: Database, tone: 'green' },
      { label: '模板', value: policy.canWriteAgents ? '可复用' : '可浏览', icon: BookOpen, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/workflow')) {
    return [
      { label: '视图', value: policy.canWriteWorkflow ? '可编排' : '可查看', icon: GitBranch, tone: 'blue' },
      { label: '链路', value: '节点化', icon: Cpu, tone: 'green' },
      { label: '状态', value: '可用', icon: Shield, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/autorepair')) {
    return [
      { label: '场景', value: '汽修', icon: Factory, tone: 'blue' },
      { label: '图谱', value: '教学', icon: Database, tone: 'green' },
      { label: '内容', value: policy.canWriteAutoRepair ? '可交互' : '可查看', icon: Bot, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/monitor')) {
    return [
      { label: '服务', value: '监测中', icon: Activity, tone: 'blue' },
      { label: '日志', value: '追踪', icon: ScrollText, tone: 'green' },
      { label: '健康', value: '巡检', icon: Zap, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/admin/platform')) {
    return [
      { label: '模型', value: policy.canWriteSettings ? '可配置' : '可查看', icon: Settings, tone: 'blue' },
      { label: '接口', value: policy.canWriteSettings ? '可管理' : '可浏览', icon: Cpu, tone: 'green' },
      { label: '状态', value: '可用', icon: Shield, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/preferences')) {
    return [
      { label: '范围', value: '仅当前账户', icon: User, tone: 'blue' },
      { label: '分区', value: '独立保存', icon: Settings, tone: 'green' },
      { label: '约束', value: '平台优先', icon: Shield, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/admin/users')) {
    return [
      { label: '用户', value: '管理', icon: User, tone: 'blue' },
      { label: '角色', value: '权限', icon: Shield, tone: 'green' },
      { label: '审计', value: hasPermission('audit:read') ? '可查' : '受限', icon: ScrollText, tone: 'amber' },
    ]
  }

  if (pathname.startsWith('/admin/audit-logs')) {
    return [
      { label: '审计', value: '追踪', icon: ScrollText, tone: 'blue' },
      { label: '用户', value: '关联', icon: User, tone: 'green' },
      { label: '安全', value: '记录', icon: Shield, tone: 'amber' },
    ]
  }

  return [
    { label: '平台', value: '在线', icon: BookOpen, tone: 'blue' },
    { label: '教学', value: '服务', icon: Bot, tone: 'green' },
    { label: '知识', value: '就绪', icon: Database, tone: 'amber' },
  ]
}

const STAT_ICON_CLASS = {
  blue: 'text-sky-400',
  green: 'text-sage-400',
  amber: 'text-amber-400',
}

// ---- 角色徽标 ----
const ROLE_META = {
  super_admin: { label: '超级管理员', color: 'text-rose-500' },
  admin: { label: '管理员', color: 'text-rose-500' },
  dept_admin: { label: '系部管理员', color: 'text-amber-600' },
  teacher: { label: '主讲教师', color: 'text-sky-600' },
  assistant: { label: '助理教师', color: 'text-sage-600' },
  student: { label: '学生', color: 'text-ink-muted' },
}

function RoleBadge({ roleName, isAdmin }) {
  const meta = ROLE_META[roleName] || (isAdmin ? ROLE_META.admin : null)
  if (!meta) return <span className="text-ink-muted">普通用户</span>
  return <span className={`font-medium ${meta.color}`}>{meta.label}</span>
}

// ---- 用户菜单下拉框 ----
function UserMenu({ user, isAdmin, roleName, dark, toggleTheme, onLogout, onPrefetch }) {
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
        aria-label={`鐢ㄦ埛鑿滃崟锛?{user?.username}`}
      >
        <div className="w-6 h-6 rounded-full bg-cloud-200 ring-1 ring-cloud-300 flex items-center justify-center">
          <User size={11} className="text-sky-500" />
        </div>
        <span className="text-xs font-medium max-w-[80px] truncate hidden sm:inline">{user?.username}</span>
        <ChevronDown size={12} className={`text-ink-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

        {open && (
          <div
            className="absolute right-0 top-full mt-1 w-52 card p-1.5 shadow-cloud-md z-50 origin-top-right menu-pop"
            role="menu"
          >
            {/* 用户信息 */}
            <div className="px-3 py-2.5 border-b border-cloud-200 mb-1">
              <p className="text-sm font-medium text-ink-primary truncate">{user?.username}</p>
              <p className="text-2xs text-ink-muted mt-0.5">
                <RoleBadge roleName={roleName} isAdmin={isAdmin} />
              </p>
            </div>

            <NavLink
              to="/preferences"
              onClick={() => setOpen(false)}
              onMouseEnter={() => onPrefetch?.('/preferences')}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-ink-body hover:bg-cloud-200 transition-colors"
              role="menuitem"
            >
              <Settings size={14} className="text-sky-500" />
              个人设置
            </NavLink>

            {/* 主题切换 */}
            <button
              onClick={() => { toggleTheme(); setOpen(false) }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-ink-body hover:bg-cloud-200 transition-colors"
              role="menuitem"
            >
              {dark ? <Sun size={14} className="text-amber-500" /> : <Moon size={14} className="text-sky-500" />}
              {dark ? '切换到浅色模式' : '切换到深色模式'}
            </button>

            {/* 退出登录 */}
            <button
              onClick={() => { onLogout(); setOpen(false) }}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-rose-500 hover:bg-rose-50 transition-colors"
              role="menuitem"
            >
              <LogOut size={14} />
              退出登录
            </button>
          </div>
        )}
    </div>
  )
}

// ---- 主应用 ----
export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const { token, user, isAdmin, roleName: authRoleName, hasPermission, logout, loading: authLoading } = useAuth()
  const [stats, setStats] = useState({ documents: 0, entities: 0, relations: 0 })
  const [toast, setToast] = useState(null)
  const toastTimerRef = useRef(null)
  const [dark, setDark] = useState(() => {
    const mode = localStorage.getItem('raganything_theme_mode')
    if (mode === 'system') return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
    const saved = localStorage.getItem('raganything_theme')
    return saved === 'dark'
  })

  const isAuthPage = location.pathname === '/login' || location.pathname === '/register'

  // 主题
  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('raganything_theme', dark ? 'dark' : 'light')
  }, [dark])

  const toggleTheme = useCallback(() => setDark(current => {
    const next = !current
    localStorage.setItem('raganything_theme_mode', next ? 'dark' : 'light')
    return next
  }), [])

  useEffect(() => {
    const onThemeChange = event => setDark(event.detail === 'dark')
    window.addEventListener('raganything-theme-change', onThemeChange)
    return () => window.removeEventListener('raganything-theme-change', onThemeChange)
  }, [])

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return undefined
    const onSystemThemeChange = event => {
      if (localStorage.getItem('raganything_theme_mode') === 'system') setDark(event.matches)
    }
    media.addEventListener?.('change', onSystemThemeChange)
    return () => media.removeEventListener?.('change', onSystemThemeChange)
  }, [])

  // 全局统计（顶栏状态条）：30s TTL 缓存、仅知识库路由、页面隐藏时跳过
  const isStatsRoute = location.pathname === '/' || location.pathname.startsWith('/knowledge')
  const loadStats = useCallback(() => {
    if (document.hidden) return
    api.getGlobalStatsCached().then(setStats).catch(() => {})
  }, [])
  useEffect(() => {
    if (!token || !isStatsRoute) return
    loadStats()
  }, [token, isStatsRoute, loadStats, location.pathname])

  const showToast = useCallback((msg, type = 'info') => {
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current)
    }
    setToast({ msg, type })
    toastTimerRef.current = setTimeout(() => {
      setToast(null)
      toastTimerRef.current = null
    }, 3000)
  }, [])

  useEffect(() => () => {
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current)
      toastTimerRef.current = null
    }
  }, [])

  const prefetchRouteChunk = useCallback((to) => {
    if (!to || globalThis.navigator?.connection?.saveData) return
    ROUTE_PREFETCH[to]?.().catch(() => {})
  }, [])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  useEffect(() => {
    const handler = () => {
      window.location.reload()
    }
    window.addEventListener('raganything:auth-expired', handler)
    return () => window.removeEventListener('raganything:auth-expired', handler)
  }, [])

  // ---- 加载中 ----
  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-cloud-100">
        <div className="text-center space-y-4 loader-pop">
          <BookOpen size={36} className="mx-auto text-sky-300 animate-float" />
          <p className="text-ink-muted text-sm font-medium">正在准备知元教学空间...</p>
        </div>
      </div>
    )
  }

  // ---- 未登录 ----
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

  const visibleNavItems = NAV_ITEMS
    .filter(item => !item.requiredPermission || hasPermission(item.requiredPermission))

  const uiPolicy = createPermissionUiPolicy(hasPermission)
  const routeMeta = getRouteMeta(location.pathname, uiPolicy)
  const cockpitStats = getCockpitStats(location.pathname, stats, hasPermission, uiPolicy)

  // ---- 主布局 ----
  return (
    <div className="min-h-screen bg-cloud-100 app-shell cockpit-shell">
      <aside className="cockpit-sidebar" aria-label="主导航">
        <NavLink to="/knowledge" className="cockpit-brand">
          <div className="cockpit-brand-mark">
            <BookOpen size={18} />
          </div>
          <div className="cockpit-brand-copy">
            <span>知元</span>
            <small>多模态教学知识服务平台</small>
          </div>
        </NavLink>

        <div className="cockpit-command-panel">
          <div className="cockpit-command-kicker">实时工作空间</div>
          <div className="cockpit-command-title">教学知识服务平台</div>
          <div className="cockpit-command-grid">
            <span />
            <span />
            <span />
          </div>
        </div>

        <nav className="cockpit-nav">
          {visibleNavItems.map(({ to, icon: Icon, label, desc }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/agents'}
              onMouseEnter={() => prefetchRouteChunk(to)}
              className={({ isActive }) => `cockpit-nav-link ${isActive ? 'active' : ''}`}
            >
              <span className="cockpit-nav-icon"><Icon size={17} /></span>
              <span className="cockpit-nav-text">
                <span>{label}</span>
                <small>{desc}</small>
              </span>
            </NavLink>
          ))}
        </nav>

      </aside>

      <header className="cockpit-topbar">
        <div className="cockpit-topbar-copy">
          <p>{routeMeta.kicker}</p>
          <h1>{routeMeta.title}</h1>
          <span>{routeMeta.subtitle}</span>
        </div>
        <div className="cockpit-topbar-actions">
          <div className="cockpit-stat-strip" aria-label="页面状态">
            {cockpitStats.map(({ label, value, icon: Icon, tone }) => (
              <div className={`cockpit-stat-chip ${tone}`} key={label}>
                <span className="cockpit-stat-icon">
                  <Icon size={15} />
                </span>
                <span className="cockpit-stat-label">{label}</span>
                <strong className="cockpit-stat-value">{value}</strong>
              </div>
            ))}
          </div>
          <UserMenu
            user={user}
            isAdmin={isAdmin}
            roleName={authRoleName}
            dark={dark}
            toggleTheme={toggleTheme}
            onLogout={handleLogout}
            onPrefetch={prefetchRouteChunk}
          />
        </div>
      </header>

      {/* ========== 顶部导航栏 ========== */}
      <header className="topnav">
        <div className="topnav-inner">
          {/* 品牌 */}
          <NavLink to="/knowledge" className="topnav-brand">
            <div className="topnav-brand-icon">
              <BookOpen size={16} className="text-white" />
            </div>
            <span className="topnav-brand-text">
              知元
            </span>
          </NavLink>

          {/* 导航链接 */}
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
                onMouseEnter={() => prefetchRouteChunk(to)}
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
                onMouseEnter={() => prefetchRouteChunk('/admin/users')}
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
                onMouseEnter={() => prefetchRouteChunk('/admin/audit-logs')}
                className={({ isActive }) =>
                  `topnav-link ${isActive ? 'active' : ''}`
                }
              >
                <ScrollText size={15} />
                <span className="hidden sm:inline">审计日志</span>
              </NavLink>
            )}
          </nav>

          {/* 右侧：统计与用户 */}
          <div className="topnav-actions">
            {/* 行内统计 */}
            <div className="hidden lg:flex items-center gap-3">
              {cockpitStats.map(({ label, value, icon: Icon, tone }) => (
                <span className="text-2xs text-ink-muted flex items-center gap-1" key={label}>
                  <Icon size={10} className={STAT_ICON_CLASS[tone] || 'text-sky-400'} />
                  {label} {value}
                </span>
              ))}
            </div>

            {/* 用户 */}
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

      {/* ========== 主内容 ========== */}
      <main className="pt-16 app-main cockpit-main">
        <div className="max-w-[1200px] mx-auto px-4 sm:px-6 py-6 sm:py-8 cockpit-content">
          <LazyErrorBoundary>
            <SuspenseWithTimeout fallback={<PageLoader />}>
              <div
                key={location.pathname}
                className="route-surface"
              >
                <Routes>
                  <Route path="/" element={<ProtectedRoute requiredPermission="kb:read"><KnowledgePage /></ProtectedRoute>} />
                  <Route path="/agents" element={<ProtectedRoute requiredPermission="agent:read"><AgentsPage onToast={showToast} /></ProtectedRoute>} />
                  <Route path="/agents/:id" element={<ProtectedRoute requiredPermission="agent:read"><AgentChatPage onToast={showToast} /></ProtectedRoute>} />
                  <Route path="/knowledge" element={<ProtectedRoute requiredPermission="kb:read"><KnowledgePage /></ProtectedRoute>} />
                  <Route path="/knowledge/:kbName" element={<ProtectedRoute requiredPermission="kb:read"><KnowledgeDetailPage /></ProtectedRoute>} />
                  <Route path="/knowledge/:kbName/documents/:docId/chunks" element={<ProtectedRoute requiredPermission="kb:read"><DocumentChunksPage /></ProtectedRoute>} />
                  <Route path="/knowledge/:kbName/documents/:docId/chunks/:chunkId" element={<ProtectedRoute requiredPermission="kb:read"><DocumentChunkDetailPage /></ProtectedRoute>} />
                  <Route path="/workflow" element={<ProtectedRoute requiredPermission="workflow:read"><WorkflowPage /></ProtectedRoute>} />
                  <Route path="/autorepair" element={<ProtectedRoute requiredPermission="autorepair:read"><AutoRepairDashboardPage /></ProtectedRoute>} />
                  <Route path="/autorepair/knowledge" element={<ProtectedRoute requiredPermission="autorepair:read"><AutoRepairKnowledgePage /></ProtectedRoute>} />
                  <Route path="/autorepair/agent" element={<ProtectedRoute requiredPermission="autorepair:write"><AutoRepairAgentPage /></ProtectedRoute>} />
                  <Route path="/settings" element={<ProtectedRoute><SettingsRedirect /></ProtectedRoute>} />
                  <Route path="/preferences" element={<ProtectedRoute><PreferencesPage onToast={showToast} /></ProtectedRoute>} />
                  <Route path="/admin/platform" element={<ProtectedRoute requiredPermission="settings:read"><AdminPlatformPage onToast={showToast} /></ProtectedRoute>} />
                  <Route path="/monitor" element={<ProtectedRoute requiredPermission="monitor:read"><MonitorPage onToast={showToast} /></ProtectedRoute>} />
                  <Route path="/admin/users" element={<ProtectedRoute requiredPermission="users:read"><AdminUsersPage /></ProtectedRoute>} />
                  <Route path="/admin/audit-logs" element={<ProtectedRoute requiredPermission="audit:read"><AdminAuditLogsPage /></ProtectedRoute>} />
                </Routes>
              </div>
            </SuspenseWithTimeout>
          </LazyErrorBoundary>
        </div>
      </main>

      {/* ========== 提示消息 ========== */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={`toast-pop fixed bottom-6 right-4 sm:right-6 px-4 py-3 rounded-xl text-sm font-medium z-50 shadow-cloud backdrop-blur-sm ${
            toast.type === 'error' ? 'toast-error' :
            toast.type === 'success' ? 'toast-success' :
            'toast-info'
          }`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}

