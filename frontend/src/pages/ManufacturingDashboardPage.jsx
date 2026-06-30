import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Factory, Cpu, Wrench, BookOpen, TrendingUp, Users, MessageSquare,
  AlertTriangle, Zap, Database, BarChart3, ChevronRight, Activity, Play
} from 'lucide-react'
import { motion } from 'framer-motion'
import { api } from '../utils/api'
import { useManufacturingKB } from '../hooks/useManufacturingKB'
import ManufacturingKBSelector from '../components/ManufacturingKBSelector'

const CARD_VARIANTS = {
  hidden: { opacity: 0, y: 12 },
  visible: i => ({ opacity: 1, y: 0, transition: { delay: i * 0.06, duration: 0.35 } }),
}

export default function ManufacturingDashboardPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [dashboard, setDashboard] = useState(null)
  const [kgSummary, setKgSummary] = useState(null)
  const [faultStats, setFaultStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const { mfgKb, setMfgKb, kbList, kbLoading, creating, createMfgKb } = useManufacturingKB()
  const genRef = useRef(0)  // generation counter: discard stale API responses on KB switch

  const loadAll = useCallback(async (showLoading = true) => {
    const gen = ++genRef.current
    if (showLoading) setLoading(true)
    setError(null)
    try {
      const [dashRes, kgRes, faultRes] = await Promise.all([
        api.get(`/manufacturing/dashboard?kb=${mfgKb}`).catch(() => null),
        api.get(`/manufacturing/knowledge-graph/summary?kb=${mfgKb}`).catch(() => null),
        api.get(`/manufacturing/fault-cases/stats?kb=${mfgKb}`).catch(() => null),
      ])
      if (gen !== genRef.current) return  // stale — newer request in flight
      setDashboard(dashRes?.data || dashRes)
      setKgSummary(kgRes?.data || kgRes)
      setFaultStats(faultRes?.data || faultRes)
    } catch (e) {
      if (gen !== genRef.current) return
      setError('数据加载失败，请确认后端服务已启动')
    } finally {
      if (gen === genRef.current && showLoading) setLoading(false)
    }
  }, [mfgKb])

  // Clear stale data on KB switch
  useEffect(() => {
    setDashboard(null)
    setKgSummary(null)
    setFaultStats(null)
  }, [mfgKb])

  // Initial data load (once on mount / when KB changes)
  useEffect(() => { loadAll(true) }, [mfgKb])

  // Smart auto-refresh: active=5s, idle=15s, hidden=stopped
  useEffect(() => {
    if (!autoRefresh) return
    let interval
    const getDelay = () => (document.visibilityState === 'visible' ? 5000 : 15000)
    const schedule = () => {
      clearInterval(interval)
      if (document.visibilityState === 'hidden') return
      interval = setInterval(() => {
        if (document.visibilityState === 'hidden') { clearInterval(interval); return }
        loadAll(false)
      }, getDelay())
    }
    schedule()
    const onVisibility = () => { if (document.visibilityState === 'visible') schedule() }
    document.addEventListener('visibilitychange', onVisibility)
    return () => { clearInterval(interval); document.removeEventListener('visibilitychange', onVisibility) }
  }, [autoRefresh, mfgKb])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center space-y-3">
          <Factory size={40} className="mx-auto text-cloud-300 animate-pulse" />
          <p className="text-sm text-ink-muted">正在加载制造智能体数据…</p>
        </motion.div>
      </div>
    )
  }

  // Detect if dashboard has any real data
  const hasData = (kgSummary?.total_nodes ?? 0) > 0
    || (faultStats?.total_cases ?? 0) > 0
    || (dashboard?.usage_stats?.total_queries ?? 0) > 0

  // Stats cards
  const statCards = [
    { label: '知识节点', value: kgSummary?.total_nodes ?? '—', icon: Database, color: 'coral', sub: `${kgSummary?.total_edges ?? '—'} 条关系` },
    { label: '故障案例', value: faultStats?.total_cases ?? '—', icon: AlertTriangle, color: 'amber', sub: `${Object.keys(faultStats?.equipment_types || {}).length || '—'} 类设备` },
    { label: '查询总量', value: dashboard?.usage_stats?.total_queries ?? '—', icon: MessageSquare, color: 'sage', sub: `日活 ${dashboard?.user_activity?.dau ?? '—'}` },
    { label: '今日查询', value: dashboard?.usage_stats?.today ?? '—', icon: TrendingUp, color: 'sky', sub: `周 ${dashboard?.usage_stats?.this_week ?? '—'}` },
  ]

  const kbStats = dashboard?.kb_stats || {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink-primary flex items-center gap-2">
            <Factory size={22} className="text-sky-500" />
            智能制造专业智能体
          </h1>
          <p className="text-sm text-ink-muted mt-1">第六届全国智能制造应用技术技能大赛 — 辅助教学系统</p>
          <div className="flex gap-1 mt-2">
            {[
              { to: '/manufacturing', label: '仪表板' },
              { to: '/manufacturing/knowledge', label: '知识库' },
              { to: '/manufacturing/agent', label: '智能体' },
            ].map(item => (
              <button key={item.to} onClick={() => navigate(item.to)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  location.pathname === item.to
                    ? 'bg-sky-50 text-sky-600'
                    : 'text-ink-muted hover:text-ink-body hover:bg-cloud-100'
                }`}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex gap-2 items-center">
          <ManufacturingKBSelector
            mfgKb={mfgKb} kbList={kbList} loading={kbLoading} creating={creating}
            onChange={setMfgKb} onCreate={createMfgKb}
          />
          <button onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
              autoRefresh ? 'bg-sage-50 border-sage-200 text-sage-600' : 'bg-cloud-100 border-cloud-300 text-ink-muted'
            }`}>
            {autoRefresh ? '自动刷新 5s' : '手动刷新'}
          </button>
          <button onClick={() => loadAll(false)} className="px-3 py-1.5 rounded-lg text-xs border border-cloud-300 text-ink-body hover:bg-cloud-200">
            刷新
          </button>
          <button onClick={() => navigate('/manufacturing/agent')}
            className="btn-primary flex items-center gap-2 px-4 py-2 text-sm">
            <Play size={15} /> 启动智能体
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="card p-4 border-rose-200 bg-rose-50 text-sm text-rose-600 flex items-center justify-between gap-2">
          <span className="flex items-center gap-2"><AlertTriangle size={16} /> {error}</span>
          <button onClick={() => loadAll(false)} className="px-3 py-1.5 rounded-xl text-xs font-medium bg-rose-100 hover:bg-rose-200 text-rose-700 transition-colors">
            重试
          </button>
        </div>
      )}

      {/* Onboarding — shown when no data at all */}
      {!loading && !error && !hasData && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="card p-8 text-center space-y-6">
          <div className="w-14 h-14 rounded-2xl bg-sky-50 flex items-center justify-center mx-auto">
            <Factory size={28} className="text-coral-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-ink-body">欢迎使用制造智能体</h3>
            <p className="text-sm text-ink-muted mt-1 max-w-md mx-auto">
              知识库尚未导入数据，请按照以下步骤开始使用
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-2xl mx-auto">
            {[
              { step: 1, icon: Database, label: '导入知识库数据', desc: '导入赛项知识、故障案例、工艺文档等', to: '/manufacturing/knowledge', btn: '浏览知识库' },
              { step: 2, icon: BarChart3, label: '构建知识图谱', desc: '系统自动构建知识节点与关系', to: '/manufacturing/knowledge', btn: '查看图谱' },
              { step: 3, icon: MessageSquare, label: '开始智能问答', desc: '基于知识库进行检索增强问答', to: '/manufacturing/agent', btn: '启动智能体' },
            ].map(item => (
              <div key={item.step} className="p-5 rounded-xl bg-cloud-200 border border-cloud-200 text-left space-y-3">
                <div className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-full bg-coral-100 flex items-center justify-center text-xs font-bold text-sky-500">
                    {item.step}
                  </div>
                  <item.icon size={18} className="text-ink-muted" />
                </div>
                <div>
                  <p className="text-sm font-medium text-ink-body">{item.label}</p>
                  <p className="text-xs text-ink-muted mt-1">{item.desc}</p>
                </div>
                <button onClick={() => navigate(item.to)}
                  className="w-full px-3 py-2 rounded-lg text-xs font-medium bg-white border border-cloud-300 text-ink-body hover:bg-sky-50 hover:border-coral-200 hover:text-sky-600 transition-colors">
                  {item.btn} →
                </button>
              </div>
            ))}
          </div>
          <p className="text-xs text-ink-muted">
            你也可以使用脚本批量导入：<code className="px-1.5 py-0.5 rounded bg-cloud-100 font-mono text-ink-muted">python scripts/import_exams.py</code>
          </p>
        </motion.div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s, i) => (
          <motion.div key={s.label} custom={i} variants={CARD_VARIANTS} initial="hidden" animate="visible"
            className="card p-5 hover:shadow-cloud-md transition-shadow cursor-default">
            <div className="flex items-start justify-between">
              {(() => {
                const colorMap = {
                  coral: { bg: 'bg-sky-50', text: 'text-sky-500' },
                  amber: { bg: 'bg-amber-50', text: 'text-amber-500' },
                  sage:  { bg: 'bg-sage-50',  text: 'text-sage-500' },
                  sky:   { bg: 'bg-sky-50',   text: 'text-sky-500' },
                }
                const c = colorMap[s.color] || colorMap.coral
                return (
                  <div className={`w-9 h-9 rounded-xl ${c.bg} flex items-center justify-center`}>
                    <s.icon size={18} className={c.text} />
                  </div>
                )
              })()}
            </div>
            <p className="text-2xl font-bold text-ink-primary mt-3">{s.value}</p>
            <p className="text-xs text-ink-muted mt-1">{s.label}</p>
            <p className="text-2xs text-ink-muted mt-0.5">{s.sub}</p>
          </motion.div>
        ))}
      </div>

      {/* Quick Actions + Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Quick Nav */}
        <motion.div custom={4} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-ink-body mb-4 flex items-center gap-2">
            <Zap size={15} className="text-amber-500" /> 快速入口
          </h3>
          <div className="space-y-1.5">
            {[
              { to: '/manufacturing/knowledge', icon: BookOpen, label: '知识图谱 & 案例库', desc: '浏览赛项知识结构、工艺文档与故障案例' },
              { to: '/manufacturing/agent', icon: MessageSquare, label: '智能问答', desc: '文本问答、代码解析、故障诊断、全局搜索' },
            ].map(item => (
              <button key={item.to} onClick={() => navigate(item.to)}
                className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-cloud-200 transition-colors text-left group">
                <div className="w-8 h-8 rounded-lg bg-cloud-100 flex items-center justify-center group-hover:bg-sky-50 transition-colors">
                  <item.icon size={15} className="text-ink-muted group-hover:text-sky-500 transition-colors" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-ink-body">{item.label}</p>
                  <p className="text-2xs text-ink-muted truncate">{item.desc}</p>
                </div>
                <ChevronRight size={14} className="text-ink-muted" />
              </button>
            ))}
          </div>
        </motion.div>

        {/* Knowledge Stats */}
        <motion.div custom={5} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-ink-body mb-4 flex items-center gap-2">
            <Database size={15} className="text-sage-500" /> 知识库规模
          </h3>
          {kbStats.knowledge_graph ? (
            <div className="space-y-3">
              <div className="flex justify-between text-xs">
                <span className="text-ink-muted">图节点</span>
                <span className="font-semibold text-ink-body">{kbStats.knowledge_graph.total_nodes}</span>
              </div>
              <div className="w-full bg-cloud-100 rounded-full h-2">
                <div className="bg-sky-400 h-2 rounded-full w-[60%]" />
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-ink-muted">图关系</span>
                <span className="font-semibold text-ink-body">{kbStats.knowledge_graph.total_edges}</span>
              </div>
              <div className="w-full bg-cloud-100 rounded-full h-2">
                <div className="bg-sage-400 h-2 rounded-full w-[40%]" />
              </div>
            </div>
          ) : (
            <p className="text-xs text-ink-muted">知识图谱数据待导入</p>
          )}
          {kbStats.process_documents && (
            <div className="mt-4 pt-3 border-t border-cloud-200">
              <p className="text-xs text-ink-muted mb-2">工艺文档分布</p>
              {Object.entries(kbStats.process_documents).slice(0, 5).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs py-0.5">
                  <span className="text-ink-body">{k}</span>
                  <span className="text-ink-muted font-medium">{v}</span>
                </div>
              ))}
            </div>
          )}
        </motion.div>

        {/* Top Queries */}
        <motion.div custom={6} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-ink-body mb-4 flex items-center gap-2">
            <TrendingUp size={15} className="text-sky-500" /> 热门查询 Top-10
          </h3>
          {(dashboard?.top_queries || []).length > 0 ? (
            <div className="space-y-1.5">
              {dashboard.top_queries.map((q, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={`font-mono w-5 text-right ${i < 3 ? 'text-sky-500 font-bold' : 'text-ink-muted'}`}>
                    {i + 1}
                  </span>
                  <span className="text-ink-body truncate flex-1">{q.query}</span>
                  <span className="text-ink-muted font-mono">{q.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-ink-muted">尚无查询数据</p>
          )}
        </motion.div>
      </div>

      {/* Usage Trend */}
      {dashboard?.query_trend && dashboard.query_trend.length > 0 && (
        <motion.div custom={7} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-ink-body mb-4 flex items-center gap-2">
            <BarChart3 size={15} className="text-sage-500" /> 7 日查询趋势
          </h3>
          <div className="flex items-end gap-2 h-24">
            {dashboard.query_trend.map((d, i) => {
              const maxCount = Math.max(...dashboard.query_trend.map(x => x.count), 1)
              const h = (d.count / maxCount) * 100
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-2xs text-ink-muted font-mono">{d.count}</span>
                  <div className="w-full bg-coral-200 rounded-t-md transition-all"
                    style={{ height: `${Math.max(h, 4)}%` }}>
                    <div className="w-full h-full bg-coral-400 rounded-t-md opacity-80" />
                  </div>
                  <span className="text-2xs text-ink-muted">{d.date.slice(5)}</span>
                </div>
              )
            })}
          </div>
        </motion.div>
      )}
    </div>
  )
}
