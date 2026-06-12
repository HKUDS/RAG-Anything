import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Factory, Cpu, Wrench, BookOpen, TrendingUp, Users, MessageSquare,
  AlertTriangle, Zap, Database, BarChart3, ChevronRight, Activity, Play
} from 'lucide-react'
import { motion } from 'framer-motion'
import { api } from '../utils/api'

const CARD_VARIANTS = {
  hidden: { opacity: 0, y: 12 },
  visible: i => ({ opacity: 1, y: 0, transition: { delay: i * 0.06, duration: 0.35 } }),
}

export default function ManufacturingDashboardPage() {
  const navigate = useNavigate()
  const [dashboard, setDashboard] = useState(null)
  const [kgSummary, setKgSummary] = useState(null)
  const [faultStats, setFaultStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const loadAll = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError(null)
    try {
      const [dashRes, kgRes, faultRes] = await Promise.all([
        api.get('/manufacturing/dashboard').catch(() => null),
        api.get('/manufacturing/knowledge-graph/summary').catch(() => null),
        api.get('/manufacturing/fault-cases/stats').catch(() => null),
      ])
      setDashboard(dashRes?.data || dashRes)
      setKgSummary(kgRes?.data || kgRes)
      setFaultStats(faultRes?.data || faultRes)
    } catch (e) {
      setError('数据加载失败，请确认后端服务已启动')
    } finally {
      if (showLoading) setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  // Smart auto-refresh: active=5s, idle=15s, hidden=stopped
  useEffect(() => {
    if (!autoRefresh) return
    let interval
    const getDelay = () => (document.visibilityState === 'visible' ? 5000 : 15000)
    const schedule = () => {
      clearInterval(interval)
      if (document.visibilityState === 'hidden') return  // stop when hidden
      loadAll(false)
      interval = setInterval(() => {
        if (document.visibilityState === 'hidden') { clearInterval(interval); return }
        loadAll(false)
      }, getDelay())
    }
    schedule()
    const onVisibility = () => { if (document.visibilityState === 'visible') schedule() }
    document.addEventListener('visibilitychange', onVisibility)
    return () => { clearInterval(interval); document.removeEventListener('visibilitychange', onVisibility) }
  }, [autoRefresh, loadAll])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center space-y-3">
          <Factory size={40} className="mx-auto text-warm-300 animate-pulse" />
          <p className="text-sm text-warm-500">正在加载制造智能体数据…</p>
        </motion.div>
      </div>
    )
  }

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
          <h1 className="text-xl font-semibold text-warm-800 flex items-center gap-2">
            <Factory size={22} className="text-coral-500" />
            智能制造专业智能体
          </h1>
          <p className="text-sm text-warm-500 mt-1">第六届全国智能制造应用技术技能大赛 — 辅助教学系统</p>
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
              autoRefresh ? 'bg-sage-50 border-sage-200 text-sage-600' : 'bg-warm-100 border-warm-200 text-warm-500'
            }`}>
            {autoRefresh ? '自动刷新 5s' : '手动刷新'}
          </button>
          <button onClick={() => loadAll(false)} className="px-3 py-1.5 rounded-lg text-xs border border-warm-200 text-warm-600 hover:bg-warm-50">
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
        <div className="card p-4 border-rose-200 bg-rose-50 text-sm text-rose-600 flex items-center gap-2">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s, i) => (
          <motion.div key={s.label} custom={i} variants={CARD_VARIANTS} initial="hidden" animate="visible"
            className="card p-5 hover:shadow-warm-md transition-shadow cursor-default">
            <div className="flex items-start justify-between">
              <div className={`w-9 h-9 rounded-xl bg-${s.color}-50 flex items-center justify-center`}>
                <s.icon size={18} className={`text-${s.color}-500`} />
              </div>
            </div>
            <p className="text-2xl font-bold text-warm-800 mt-3">{s.value}</p>
            <p className="text-xs text-warm-500 mt-1">{s.label}</p>
            <p className="text-2xs text-warm-400 mt-0.5">{s.sub}</p>
          </motion.div>
        ))}
      </div>

      {/* Quick Actions + Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Quick Nav */}
        <motion.div custom={4} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-warm-700 mb-4 flex items-center gap-2">
            <Zap size={15} className="text-amber-500" /> 快速入口
          </h3>
          <div className="space-y-1.5">
            {[
              { to: '/manufacturing/knowledge', icon: BookOpen, label: '知识图谱 & 案例库', desc: '浏览赛项知识结构、工艺文档与故障案例' },
              { to: '/manufacturing/agent', icon: MessageSquare, label: '智能问答', desc: '文本问答、代码解析、故障诊断' },
              { to: '/query', icon: Activity, label: 'RAG 全局查询', desc: '使用已有检索引擎搜索全库' },
            ].map(item => (
              <button key={item.to} onClick={() => navigate(item.to)}
                className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-warm-50 transition-colors text-left group">
                <div className="w-8 h-8 rounded-lg bg-warm-100 flex items-center justify-center group-hover:bg-coral-50 transition-colors">
                  <item.icon size={15} className="text-warm-500 group-hover:text-coral-500 transition-colors" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-warm-700">{item.label}</p>
                  <p className="text-2xs text-warm-500 truncate">{item.desc}</p>
                </div>
                <ChevronRight size={14} className="text-warm-400" />
              </button>
            ))}
          </div>
        </motion.div>

        {/* Knowledge Stats */}
        <motion.div custom={5} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-warm-700 mb-4 flex items-center gap-2">
            <Database size={15} className="text-sage-500" /> 知识库规模
          </h3>
          {kbStats.knowledge_graph ? (
            <div className="space-y-3">
              <div className="flex justify-between text-xs">
                <span className="text-warm-500">图节点</span>
                <span className="font-semibold text-warm-700">{kbStats.knowledge_graph.total_nodes}</span>
              </div>
              <div className="w-full bg-warm-100 rounded-full h-2">
                <div className="bg-coral-400 h-2 rounded-full" style={{ width: '60%' }} />
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-warm-500">图关系</span>
                <span className="font-semibold text-warm-700">{kbStats.knowledge_graph.total_edges}</span>
              </div>
              <div className="w-full bg-warm-100 rounded-full h-2">
                <div className="bg-sage-400 h-2 rounded-full" style={{ width: '40%' }} />
              </div>
            </div>
          ) : (
            <p className="text-xs text-warm-400">知识图谱数据待导入</p>
          )}
          {kbStats.process_documents && (
            <div className="mt-4 pt-3 border-t border-warm-100">
              <p className="text-xs text-warm-500 mb-2">工艺文档分布</p>
              {Object.entries(kbStats.process_documents).slice(0, 5).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs py-0.5">
                  <span className="text-warm-600">{k}</span>
                  <span className="text-warm-500 font-medium">{v}</span>
                </div>
              ))}
            </div>
          )}
        </motion.div>

        {/* Top Queries */}
        <motion.div custom={6} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-warm-700 mb-4 flex items-center gap-2">
            <TrendingUp size={15} className="text-coral-500" /> 热门查询 Top-10
          </h3>
          {(dashboard?.top_queries || []).length > 0 ? (
            <div className="space-y-1.5">
              {dashboard.top_queries.map((q, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={`font-mono w-5 text-right ${i < 3 ? 'text-coral-500 font-bold' : 'text-warm-400'}`}>
                    {i + 1}
                  </span>
                  <span className="text-warm-600 truncate flex-1">{q.query}</span>
                  <span className="text-warm-400 font-mono">{q.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-warm-400">尚无查询数据</p>
          )}
        </motion.div>
      </div>

      {/* Usage Trend */}
      {dashboard?.query_trend && dashboard.query_trend.length > 0 && (
        <motion.div custom={7} variants={CARD_VARIANTS} initial="hidden" animate="visible"
          className="card p-5">
          <h3 className="text-sm font-semibold text-warm-700 mb-4 flex items-center gap-2">
            <BarChart3 size={15} className="text-sage-500" /> 7 日查询趋势
          </h3>
          <div className="flex items-end gap-2 h-24">
            {dashboard.query_trend.map((d, i) => {
              const maxCount = Math.max(...dashboard.query_trend.map(x => x.count), 1)
              const h = (d.count / maxCount) * 100
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-2xs text-warm-500 font-mono">{d.count}</span>
                  <div className="w-full bg-coral-200 rounded-t-md transition-all"
                    style={{ height: `${Math.max(h, 4)}%` }}>
                    <div className="w-full h-full bg-coral-400 rounded-t-md opacity-80" />
                  </div>
                  <span className="text-2xs text-warm-400">{d.date.slice(5)}</span>
                </div>
              )
            })}
          </div>
        </motion.div>
      )}
    </div>
  )
}
