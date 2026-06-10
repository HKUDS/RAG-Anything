import { useState, useEffect } from 'react'
import { Clock, Zap, BarChart3, Terminal, Cpu, TrendingUp } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../utils/api'

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
    { name: '实体提取', count: llmStats.extract_calls || 0, fill: '#e8734a' },
    { name: '其他调用', count: llmStats.other_calls || 0, fill: '#5b9bd5' },
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
          { icon: Zap, label: 'LLM 总调用', val: llmStats.total_cache_entries || 0, color: 'text-coral-500' },
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
        <div className="card p-4">
          <h3 className="text-sm font-medium text-warm-700 mb-3">LLM 调用分布</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <XAxis dataKey="name" tick={{ fill: '#8a8276', fontSize: 12, fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <YAxis tick={{ fill: '#8a8276', fontSize: 12, fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <Tooltip contentStyle={{ background: '#ffffff', border: '1px solid #e8e2d6', borderRadius: '12px', color: '#4a433b', fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif", boxShadow: '0 4px 16px rgba(74,67,59,0.08)' }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} fill="#e8734a" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card p-4 space-y-2">
          <h3 className="text-sm font-medium text-warm-700 mb-3">处理时间线</h3>
          <div className="space-y-2 max-h-52 overflow-y-auto">
            {(logs || []).slice().reverse().slice(0, 15).map((e, i) => (
              <div key={i} className="flex items-start gap-3 text-xs">
                <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-coral-400"/>
                <div>
                  <span className="text-warm-500 font-mono">{e.time?.slice(11, 19) || ''}</span>
                  <span className="text-coral-500 ml-2 font-medium">{e.event}</span>
                  <span className="text-warm-500 ml-2">{e.file || ''}</span>
                  {e.error && <p className="text-rose-500 mt-0.5">{e.error.slice(0, 80)}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Live Log */}
      <div className="card p-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700 mb-3">
          <Terminal size={14}/> 实时日志
        </h3>
        <div className="bg-warm-50 rounded-xl p-4 font-mono text-xs text-warm-500 h-48 overflow-y-auto space-y-1 border border-warm-200/60">
          {(logs || []).slice().reverse().slice(0, 20).map((e, i) => (
            <div key={i}>
              <span className="text-warm-500">[{e.time?.slice(0, 19) || '?'}]</span>{' '}
              <span className={e.event?.includes('error') ? 'text-rose-500 font-medium' : 'text-coral-500 font-medium'}>{e.event}</span>{' '}
              <span className="text-warm-500">{e.file || e.task_id || ''}</span>
            </div>
          ))}
          {(!logs || logs.length === 0) && (
            <div className="text-center py-8">
              <span className="text-warm-500 text-sm">等待事件...</span>
              <p className="text-warm-500 text-xs mt-1">系统事件将实时显示在这里 📡</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
