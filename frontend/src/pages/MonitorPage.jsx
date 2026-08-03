import { useEffect, useState } from 'react'
import {
  CirclePause, Database, HardDrive, Loader2, Pin, PinOff,
  RefreshCw, Server, Terminal, Trash2, TrendingUp, Zap,
} from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../utils/api'
import { formatDate } from '../utils/dateFormat'
import { useAuth } from '../context/AuthContext'

// 图表颜色：Recharts 需要十六进制字面量，全部取自 DESIGN.md
const CHART_INK = '#557a95'
const CHART_SKY = '#5b9bd5'
const CHART_CORAL = '#e8734a'
const CHART_SURFACE = '#ffffff'
const CHART_BORDER = '#d6e5f2'
const CHART_TEXT = '#2d4d66'
const CHART_SHADOW = 'rgba(38,72,96,0.06)'
const CHART_FONT_FAMILY = "'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"

const formatPercent = value => `${Math.round((Number(value) || 0) * 100)}%`
const STATUS_LABELS = {
  ok: '正常',
  degraded: '降级',
  low: '空间偏低',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  queued: '排队中',
  deleted: '已删除',
}

const EVENT_LABELS = {
  upload_start: '开始上传',
  upload_complete: '上传完成',
  upload_error: '上传失败',
  upload_delete: '删除上传任务',
  url_download_start: '开始下载链接文件',
  url_download_complete: '链接文件下载完成',
  url_process_complete: '链接文件处理完成',
  url_error: '链接处理失败',
  graph_entity_create: '创建图谱实体',
  graph_entity_rename: '重命名图谱实体',
  graph_entity_delete: '删除图谱实体',
  graph_edge_create: '创建图谱关系',
  graph_edge_delete: '删除图谱关系',
  doc_delete: '删除文档',
  reprocess_multimodal_done: '多模态补处理完成',
  kb_cache_reload: '刷新知识库缓存',
  kb_cache_evict: '淘汰知识库缓存',
  kb_cache_pin: '固定知识库缓存',
  kb_cache_unpin: '取消固定知识库缓存',
}

function formatDisplayValue(value) {
  if (value === undefined || value === null || value === '') return '未知'
  if (typeof value !== 'string') return String(value)

  const normalized = value.trim()
  const lower = normalized.toLowerCase()
  if (STATUS_LABELS[lower]) return STATUS_LABELS[lower]
  if (lower.startsWith('error:')) {
    const detail = normalized.slice(normalized.indexOf(':') + 1).trim()
    return detail ? `异常：${detail}` : '异常'
  }
  return normalized
}

function formatEventLabel(event) {
  return EVENT_LABELS[event] || event || '未知事件'
}

function getValueTone(rawValue) {
  if (typeof rawValue !== 'string') return 'default'
  const normalized = rawValue.trim().toLowerCase()
  if (normalized.includes('error') || normalized === 'failed') return 'error'
  if (normalized === 'low' || normalized === 'degraded') return 'warning'
  return 'default'
}

function isEventError(event, error) {
  return Boolean(error) || String(event || '').toLowerCase().includes('error')
}

function HealthPill({ label, value, rawValue = value }) {
  const tone = getValueTone(rawValue)
  return (
    <div className={`rounded-xl border px-3 py-2 ${
      tone === 'error'
        ? 'border-rose-200 bg-rose-50 text-rose-600'
        : tone === 'warning'
          ? 'border-amber-200 bg-amber-50 text-amber-600'
          : 'border-cloud-300 bg-cloud-50 text-ink-body'
    }`}>
      <p className="text-2xs opacity-80">{label}</p>
      <p className="text-sm font-medium mt-0.5 break-all">{formatDisplayValue(value)}</p>
    </div>
  )
}

export default function MonitorPage({ onToast }) {
  const { hasPermission } = useAuth()
  const canMaintain = hasPermission('settings:write')
  const [status, setStatus] = useState({ tasks: [], events: [] })
  const [llmStats, setLLMStats] = useState({ total_cache_entries: 0, extract_calls: 0, other_calls: 0 })
  const [logs, setLogs] = useState([])
  const [health, setHealth] = useState(null)
  const [cacheStats, setCacheStats] = useState(null)
  const [maintaining, setMaintaining] = useState('')

  const loadMonitorData = async () => {
    const [s, l, log, h, cache] = await Promise.all([
      api.getStatus().catch(() => ({})),
      api.getLLMStats().catch(() => ({})),
      api.getLogs(30).catch(() => ({ events: [] })),
      api.health().catch(err => ({ status: 'degraded', components: { health: err.message } })),
      api.getCacheStats().catch(() => null),
    ])
    setStatus(s)
    setLLMStats(l)
    setLogs(log.events || [])
    setHealth(h)
    setCacheStats(cache)
  }

  useEffect(() => {
    loadMonitorData()
    const timer = setInterval(loadMonitorData, 5000)
    return () => clearInterval(timer)
  }, [])

  const runMaintenance = async (action, kbName) => {
    if (!canMaintain) {
      onToast?.('你的角色没有维护权限，需要“设置写入”权限（settings:write）', 'error')
      return
    }
    const key = `${action}:${kbName}`
    setMaintaining(key)
    try {
      const handlers = {
        reload: api.reloadKB,
        evict: api.evictKB,
        pin: api.pinKB,
        unpin: api.unpinKB,
      }
      const result = await handlers[action](kbName)
      onToast?.(result?.message || '操作已完成', result?.status === 'ok' ? 'success' : 'info')
      await loadMonitorData()
    } catch (e) {
      onToast?.(e.message, 'error')
    } finally {
      setMaintaining('')
    }
  }

  const chartData = [
    { name: '实体提取', count: llmStats.extract_calls || 0, fill: CHART_CORAL },
    { name: '其他调用', count: llmStats.other_calls || 0, fill: CHART_SKY },
  ]
  const components = health?.components || {}
  const cachedKbs = cacheStats?.cached_kbs || []
  const pinned = new Set(cacheStats?.pinned || [])

  return (
    <div className="space-y-8">
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">监控面板</h2>
          <p className="page-subtitle">实时系统状态、缓存维护和使用统计</p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {[
          { icon: Zap, label: '模型缓存条目', val: llmStats.total_cache_entries || llmStats.cache_entries || 0, color: 'text-sky-500' },
          { icon: TrendingUp, label: '实体提取', val: llmStats.extract_calls || 0, color: 'text-sage-500' },
          { icon: Server, label: '服务状态', val: health?.status || '检测中', color: health?.status === 'degraded' ? 'text-amber-500' : 'text-sky-500' },
          { icon: Database, label: '知识库缓存', val: cacheStats?.total_cached ?? 0, color: 'text-amber-500' },
        ].map(({ icon: Icon, label, val, color }) => {
          const isNumericValue = typeof val === 'number'

          return (
            <div key={label} className="stat-card">
              <div className="flex items-center gap-2 stat-label">
                <Icon size={14}/> {label}
              </div>
              <p className={`stat-value ${isNumericValue ? 'stat-value-number monitor-stat-value-number' : 'stat-value-text'} ${color}`}>
                {isNumericValue ? val.toLocaleString() : formatDisplayValue(val)}
              </p>
            </div>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <section className="card p-4 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30">
          <div className="flex items-center justify-between gap-3">
            <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
              <Server size={14}/> 健康检查
            </h3>
            <button className="btn-secondary text-xs py-1.5 px-3" onClick={loadMonitorData}>
              <RefreshCw size={13}/> 刷新
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <HealthPill label="服务" value={components.server || health?.status || '检测中'} />
            <HealthPill label="当前知识库" value={components.active_kb || '未选择'} />
            <HealthPill label="知识库数量" value={components.kb_count ?? '未知'} />
            <HealthPill label="认证数据库" value={components.auth_db || '未知'} />
            <HealthPill label="监控日志" value={components.monitor_logs || '未知'} />
            <HealthPill label="磁盘剩余" value={components.disk_free_gb !== undefined ? `${components.disk_free_gb} GB` : '未知'} />
            {components.disk_warning && <HealthPill label="磁盘警告" value={components.disk_warning} />}
          </div>
        </section>

        <section className="card p-4 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
              <HardDrive size={14}/> 知识库缓存维护
            </h3>
            <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
              缓存维护会影响下次查询加载速度；固定缓存可避免高频知识库被自动淘汰。
            </p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <HealthPill label="缓存数量" value={`${cacheStats?.total_cached ?? 0}/${cacheStats?.max_size ?? '-'}`} />
            <HealthPill label="命中率" value={formatPercent(cacheStats?.hit_rate)} />
            <HealthPill label="固定知识库" value={cacheStats?.pinned_count ?? 0} />
            <HealthPill label="淘汰次数" value={cacheStats?.evictions ?? 0} />
          </div>
          {!canMaintain && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              当前角色可查看监控，但维护操作需要“设置写入”权限（settings:write）。
            </div>
          )}
          <div className="space-y-2 max-h-52 overflow-y-auto">
            {cachedKbs.map(kb => {
              const isPinned = pinned.has(kb)
              return (
                <div key={kb} className="flex items-center justify-between gap-3 rounded-xl bg-cloud-100 dark:bg-sky-950/50 border border-cloud-200 dark:border-sky-800/30 px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink-body dark:text-cloud-300 truncate">{kb}</p>
                    <p className="text-2xs text-ink-muted dark:text-cloud-500">{isPinned ? '已固定到缓存' : '可自动淘汰'}</p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      className="btn-secondary text-xs py-1 px-2"
                      disabled={!canMaintain || maintaining === `reload:${kb}`}
                      onClick={() => runMaintenance('reload', kb)}
                      title="清除实例缓存，下次重新加载"
                    >
                      {maintaining === `reload:${kb}` ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    </button>
                    <button
                      className="btn-secondary text-xs py-1 px-2"
                      disabled={!canMaintain || maintaining === `${isPinned ? 'unpin' : 'pin'}:${kb}`}
                      onClick={() => runMaintenance(isPinned ? 'unpin' : 'pin', kb)}
                      title={isPinned ? '取消固定' : '固定缓存'}
                    >
                      {isPinned ? <PinOff size={12} /> : <Pin size={12} />}
                    </button>
                    <button
                      className="btn-secondary text-xs py-1 px-2 text-rose-600 border-rose-200"
                      disabled={!canMaintain || isPinned || maintaining === `evict:${kb}`}
                      onClick={() => runMaintenance('evict', kb)}
                      title={isPinned ? '已固定的知识库不能淘汰' : '淘汰缓存'}
                    >
                      {maintaining === `evict:${kb}` ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                    </button>
                  </div>
                </div>
              )
            })}
            {cachedKbs.length === 0 && (
              <div className="text-center py-6 text-sm text-ink-muted dark:text-cloud-500">
                暂无已缓存的知识库实例
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="card p-4 dark:bg-sky-900/20 dark:border-sky-800/30">
          <h3 className="text-sm font-medium text-ink-body dark:text-cloud-300 mb-3">模型调用分布</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <XAxis dataKey="name"
                tick={{ fill: CHART_INK, fontSize: 13, fontFamily: CHART_FONT_FAMILY }} />
              <YAxis
                tick={{ fill: CHART_INK, fontSize: 13, fontFamily: CHART_FONT_FAMILY }} />
              <Tooltip contentStyle={{
                background: CHART_SURFACE,
                border: `1px solid ${CHART_BORDER}`,
                borderRadius: '12px',
                color: CHART_TEXT,
                fontFamily: CHART_FONT_FAMILY,
                boxShadow: `0 4px 16px ${CHART_SHADOW}`,
              }} formatter={value => [typeof value === 'number' ? value.toLocaleString() : value, '调用次数']} />
              <Bar dataKey="count" name="调用次数" radius={[4, 4, 0, 0]} fill={CHART_CORAL} />
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
                  <span className="text-sky-500 dark:text-sky-400 ml-2 font-medium">{formatEventLabel(e.event)}</span>
                  <span className="text-ink-muted dark:text-cloud-500 ml-2">{e.file || ''}</span>
                  {e.error && <p className="text-rose-500 mt-0.5">{e.error.slice(0, 80)}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card p-4 dark:bg-sky-900/20 dark:border-sky-800/30">
        <div className="mb-3">
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
            <Terminal size={14}/> 监控日志
          </h3>
          <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
            最近事件会持久化保存，服务重启后仍可查看。
          </p>
        </div>
        <div className="bg-cloud-100 dark:bg-sky-950/60 rounded-xl p-4 font-mono text-xs text-ink-muted dark:text-cloud-500 h-48 overflow-y-auto space-y-1 border border-cloud-200 dark:border-sky-800/30">
          {(logs || []).slice().reverse().slice(0, 20).map((e, i) => (
            <div key={i}>
              <span className="text-ink-muted dark:text-cloud-500">[{formatDate(e.time) || '?'}]</span>{' '}
              <span className={isEventError(e.event, e.error) ? 'text-rose-500 font-medium' : 'text-sky-500 dark:text-sky-400 font-medium'}>{formatEventLabel(e.event)}</span>{' '}
              <span className="text-ink-muted dark:text-cloud-500">{e.file || e.task_id || ''}</span>
            </div>
          ))}
          {(!logs || logs.length === 0) && (
            <div className="text-center py-8">
              <CirclePause size={18} className="mx-auto mb-2 text-ink-muted dark:text-cloud-500" />
              <span className="text-ink-muted dark:text-cloud-500 text-sm">等待事件...</span>
              <p className="text-ink-muted dark:text-cloud-500 text-xs mt-1">系统事件将实时显示在这里</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
