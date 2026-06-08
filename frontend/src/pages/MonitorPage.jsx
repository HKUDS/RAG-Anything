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
    { name: '实体提取', count: llmStats.extract_calls || 0, fill: '#3b82f6' },
    { name: '其他调用', count: llmStats.other_calls || 0, fill: '#6366f1' },
  ]

  return (
    <div className="space-y-6">
      <h2 className="font-display text-xl font-bold text-slate-100">监控面板</h2>

      {/* Metrics Cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { icon: Zap, label: 'LLM 总调用', val: llmStats.total_cache_entries || 0, color: 'text-neon-400' },
          { icon: TrendingUp, label: '实体提取', val: llmStats.extract_calls || 0, color: 'text-emerald-400' },
          { icon: Cpu, label: '处理任务', val: (status.tasks || []).length, color: 'text-amber-400' },
          { icon: BarChart3, label: '事件记录', val: (logs || []).length, color: 'text-purple-400' },
        ].map(({ icon: Icon, label, val, color }) => (
          <div key={label} className="glass p-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <Icon size={14}/> {label}
            </div>
            <p className={`text-2xl font-display font-bold mt-1 ${color}`}>{val}</p>
          </div>
        ))}
      </div>

      {/* Chart + Tasks Row */}
      <div className="grid grid-cols-2 gap-4">
        <div className="glass p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">LLM 调用分布</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12, fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 12, fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontFamily: "'Microsoft YaHei', 'SimHei', 'PingFang SC', sans-serif" }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]} fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="glass p-4 space-y-2">
          <h3 className="text-sm font-medium text-slate-300 mb-3">处理时间线</h3>
          <div className="space-y-2 max-h-52 overflow-y-auto">
            {(logs || []).slice().reverse().slice(0, 15).map((e, i) => (
              <div key={i} className="flex items-start gap-3 text-xs">
                <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-neon-500"/>
                <div>
                  <span className="text-slate-500 font-mono">{e.time?.slice(11, 19) || ''}</span>
                  <span className="text-neon-400 ml-2">{e.event}</span>
                  <span className="text-slate-600 ml-2">{e.file || ''}</span>
                  {e.error && <p className="text-red-400 mt-0.5">{e.error.slice(0, 80)}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Live Log */}
      <div className="glass p-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-3">
          <Terminal size={14}/> 实时日志
        </h3>
        <div className="bg-ink-900 rounded-lg p-4 font-mono text-xs text-slate-400 h-48 overflow-y-auto space-y-1">
          {(logs || []).slice().reverse().slice(0, 20).map((e, i) => (
            <div key={i}>
              <span className="text-slate-600">[{e.time?.slice(0, 19) || '?'}]</span>{' '}
              <span className={e.event?.includes('error') ? 'text-red-400' : 'text-neon-400'}>{e.event}</span>{' '}
              <span className="text-slate-500">{e.file || e.task_id || ''}</span>
            </div>
          ))}
          {(!logs || logs.length === 0) && <span className="text-slate-600">等待事件…</span>}
        </div>
      </div>
    </div>
  )
}
