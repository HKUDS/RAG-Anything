import { useState, useEffect } from 'react'
import { Clock, Zap, BarChart3, Terminal, Cpu, TrendingUp } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../utils/api'

// Chart colors — literal hex values required by Recharts; all drawn from DESIGN.md
const CHART_INK = '#557a95'       // ink-muted
const CHART_SKY = '#5b9bd5'       // sky-500
const CHART_CORAL = '#e8734a'     // coral-500 (warm accent for data viz)
const CHART_SURFACE = '#ffffff'   // cloud-surface
const CHART_BORDER = '#d6e5f2'    // cloud-border
const CHART_TEXT = '#2d4d66'      // ink-body
const CHART_SHADOW = 'rgba(38,72,96,0.06)' // ink-primary at 0.06

export default function MonitorPage() {
  const [status, setStatus] = useState({ tasks: [], events: [] })
  const [llmStats, setLLMStats] = useState({ total_cache_entries: 0, extract_calls: 0, other_calls: 0 })
  const [logs, setLogs] = useState([])

  useEffect(() => {
    const fetch = async () => {
      const [s, l, log] = await Promise.all([
        api.getStatus().catch(() => ({})),
        api.getLLMStats().catch(() => ({})),
        api.getLogs(30).catch(() => ({ events: [] })),
      ])
      setStatus(s); setLLMStats(l); setLogs(log.events || [])
    }
    fetch()
    const timer = setInterval(fetch, 5000)
    return () => clearInterval(timer)
  }, [])

  const chartData = [
    { name: '实体提取', count: llmStats.extract_calls || 0, fill: CHART_CORAL },
    { name: '其他调用', count: llmStats.other_calls || 0, fill: CHART_SKY },
  ]

  return (
    <div className="space-y-8">
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">📈 监控面板</h2>
          <p className="page-subtitle">实时系统状态和使用统计</p>
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-4 gap-5">
        {[
          { icon: Zap, label: 'LLM 总调用', val: llmStats.total_cache_entries || 0, color: 'text-sky-500' },
          { icon: TrendingUp, label: '实体提取', val: llmStats.extract_calls || 0, color: 'text-sage-500' },
          { icon: Cpu, label: '处理任务', val: (status.tasks || []).length, color: 'text-amber-500' },
          { icon: BarChart3, label: '事件记录', val: (logs || []).length, color: 'text-sky-500' },
        ].map(({ icon: Icon, label, val, color }) => (
          <div key={label} className="stat-card">
            <div className="flex items-center gap-2 stat-label mb-1">
              <Icon size={14}/> {label}
            </div>
            <p className={`stat-value ${color}`}>{val}</p>
          </div>
        ))}
      </div>

      {/* Chart + Tasks Row */}
      <div className="grid grid-cols-2 gap-5">
        <div className="card p-4 dark:bg-sky-900/20 dark:border-sky-800/30">
          <h3 className="text-sm font-medium text-ink-body dark:text-cloud-300 mb-3">LLM 调用分布</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <XAxis dataKey="name"
                tick={{ fill: CHART_INK, fontSize: 13, fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <YAxis
                tick={{ fill: CHART_INK, fontSize: 13, fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <Tooltip contentStyle={{
                background: CHART_SURFACE,
                border: `1px solid ${CHART_BORDER}`,
                borderRadius: '12px',
                color: CHART_TEXT,
                fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif",
                boxShadow: `0 4px 16px ${CHART_SHADOW}`,
              }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} fill={CHART_CORAL} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card p-4 space-y-2 dark:bg-sky-900/20 dark:border-sky-800/30">
          <h3 className="text-sm font-medium text-ink-body dark:text-cloud-300 mb-3">处理时间线</h3>
          <div className="space-y-2 max-h-52 overflow-y-auto">
            {(logs || []).slice().reverse().slice(0, 15).map((e, i) => (
              <div key={i} className="flex items-start gap-3 text-xs">
                <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-sky-400"/>
                <div>
                  <span className="text-ink-muted dark:text-cloud-500 font-mono">{e.time?.slice(11, 19) || ''}</span>
                  <span className="text-sky-500 dark:text-sky-400 ml-2 font-medium">{e.event}</span>
                  <span className="text-ink-muted dark:text-cloud-500 ml-2">{e.file || ''}</span>
                  {e.error && <p className="text-rose-500 mt-0.5">{e.error.slice(0, 80)}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Live Log */}
      <div className="card p-4 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300 mb-3">
          <Terminal size={14}/> 实时日志
        </h3>
        <div className="bg-cloud-100 dark:bg-sky-950/60 rounded-xl p-4 font-mono text-xs text-ink-muted dark:text-cloud-500 h-48 overflow-y-auto space-y-1 border border-cloud-200 dark:border-sky-800/30">
          {(logs || []).slice().reverse().slice(0, 20).map((e, i) => (
            <div key={i}>
              <span className="text-ink-muted dark:text-cloud-500">[{e.time?.slice(0, 19) || '?'}]</span>{' '}
              <span className={e.event?.includes('error') ? 'text-rose-500 font-medium' : 'text-sky-500 dark:text-sky-400 font-medium'}>{e.event}</span>{' '}
              <span className="text-ink-muted dark:text-cloud-500">{e.file || e.task_id || ''}</span>
            </div>
          ))}
          {(!logs || logs.length === 0) && (
            <div className="text-center py-8">
              <span className="text-ink-muted dark:text-cloud-500 text-sm">等待事件...</span>
              <p className="text-ink-muted dark:text-cloud-500 text-xs mt-1">系统事件将实时显示在这里 📡</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
