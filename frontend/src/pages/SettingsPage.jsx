import { useEffect, useState } from 'react'
import {
  AlertCircle, Cpu, Database, Gauge, Info, Lock, Route, Save, Search, Server,
  RotateCcw, ShieldCheck, Sliders, TestTube2,
} from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../context/AuthContext'

const RRF_DEFAULTS = {
  rrf_k: 60,
  bm25_top_k: 50,
  vector_top_k: 100,
  graph_top_k: 30,
  graph_depth: 2,
  bm25_k1: 1.5,
  bm25_b: 0.75,
  bm25_tokenizer: 'jieba',
  rrf_channel_timeout: 0.15,
  enabled_channels: 'bm25,vector,graph',
}

const mergeSettings = settings => {
  const rrf = { ...RRF_DEFAULTS, ...(settings?.rrf || {}) }
  if (!String(rrf.bm25_tokenizer || '').trim()) rrf.bm25_tokenizer = RRF_DEFAULTS.bm25_tokenizer
  return { ...settings, rrf }
}

const PROCESSING_DEFAULT_FIELDS = [
  { key: 'parser', label: '默认解析器', value: v => v || 'docling' },
  { key: 'chunking_strategy', label: '默认分块策略', value: v => v || 'recursive' },
  { key: 'chunk_size', label: '默认切块大小', value: v => `${v || 800} tokens` },
  { key: 'enable_image', label: '默认图片处理', value: v => (v ?? true) ? '开启' : '关闭' },
  { key: 'enable_table', label: '默认表格处理', value: v => (v ?? true) ? '开启' : '关闭' },
  { key: 'enable_equation', label: '默认公式处理', value: v => (v ?? true) ? '开启' : '关闭' },
  { key: 'enable_video', label: '默认视频处理', value: v => (v ?? false) ? '开启' : '关闭' },
]

const RRF_NUMBER_FIELDS = [
  ['rrf_k', 'RRF K', 1, 200, 1],
  ['bm25_top_k', 'BM25 Top K', 1, 500, 1],
  ['vector_top_k', '向量 Top K', 1, 500, 1],
  ['graph_top_k', '图谱 Top K', 1, 200, 1],
  ['graph_depth', '图谱深度', 1, 5, 1],
  ['bm25_k1', 'BM25 k1', 0.1, 3, 0.1],
  ['bm25_b', 'BM25 b', 0, 1, 0.05],
  ['rrf_channel_timeout', '通道超时（秒）', 0.05, 5, 0.05],
]

function Field({ label, children, hint }) {
  return (
    <div>
      <label className="text-xs text-ink-muted dark:text-cloud-500">{label}</label>
      <div className="mt-1">{children}</div>
      {hint && <p className="text-2xs text-ink-muted dark:text-cloud-500 mt-1">{hint}</p>}
    </div>
  )
}

function ReadonlyItem({ label, value }) {
  return (
    <div className="rounded-xl border border-cloud-300/70 dark:border-sky-800/30 bg-cloud-50 dark:bg-sky-900/20 px-3 py-2">
      <p className="text-2xs text-ink-muted dark:text-cloud-500">{label}</p>
      <p className="text-sm text-ink-body dark:text-cloud-300 font-medium mt-0.5 break-all">{value || '未配置'}</p>
    </div>
  )
}

export default function SettingsPage({ onToast }) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission('settings:write')
  const [local, setLocal] = useState(() => mergeSettings({}))
  const [testing, setTesting] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [savingKey, setSavingKey] = useState('')

  useEffect(() => {
    api.getSettings()
      .then(s => setLocal(mergeSettings(s)))
      .catch(err => {
        console.error('加载设置失败:', err)
        onToast?.(`加载设置失败: ${err.message}`, 'error')
      })
  }, [])

  const save = async (partial, key = 'settings') => {
    if (!canWrite) {
      onToast?.('你的角色只有查看权限，不能修改平台设置', 'error')
      return
    }
    setSavingKey(key)
    try {
      const result = await api.updateSettings(partial)
      onToast?.(result?.note || '设置已更新', 'success')
    } catch (e) {
      onToast?.(e.message, 'error')
    } finally {
      setSavingKey('')
    }
  }

  const saveRrfField = (key, value) => {
    const next = { ...(local.rrf || RRF_DEFAULTS), [key]: value }
    setLocal(prev => ({ ...prev, rrf: next }))
    save({ [key]: value }, key)
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      const health = await api.health()
      const status = health?.status || 'ok'
      onToast?.(`服务连接正常: ${status}`, 'success')
    } catch (e) {
      onToast?.(`连接失败: ${e.message}`, 'error')
    } finally {
      setTesting(false)
    }
  }

  const resetToDefaults = async () => {
    if (!canWrite || savingKey || resetting) return
    if (!window.confirm('确认恢复系统设置默认值吗？这会重置当前页可编辑项，并以服务启动时的默认配置为准。')) return
    setResetting(true)
    try {
      const result = await api.resetSettings()
      setLocal(mergeSettings(result?.settings || {}))
      onToast?.(result?.note || '已恢复默认设置', 'success')
    } catch (e) {
      onToast?.(e.message, 'error')
    } finally {
      setResetting(false)
    }
  }

  const disabled = !canWrite || Boolean(savingKey) || resetting
  const rrf = local.rrf || RRF_DEFAULTS

  return (
    <div className="settings-page w-full max-w-none grid grid-cols-1 xl:grid-cols-12 gap-5 xl:gap-6 items-stretch">
      <div className="page-header page-header-divider flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between xl:col-span-12">
        <div>
          <h2 className="page-title">平台设置</h2>
          <p className="page-subtitle">管理模型接口、检索调优、运行限制和平台级默认值</p>
        </div>
        {canWrite && (
          <button
            className="btn-secondary text-sm flex items-center gap-2 shrink-0"
            onClick={resetToDefaults}
            disabled={disabled}
            title="恢复当前系统设置到服务启动时的默认值"
          >
            <RotateCcw size={14} />
            {resetting ? '恢复中...' : '恢复默认'}
          </button>
        )}
      </div>

      {!canWrite && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 dark:border-amber-800/30 bg-amber-50 dark:bg-amber-900/20 p-4 xl:col-span-12">
          <Lock size={16} className="text-amber-500 dark:text-amber-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">当前为只读视图</p>
            <p className="text-xs text-amber-700/80 dark:text-amber-300/80 mt-1">
              你可以查看平台配置；修改模型、检索和运行参数需要 settings:write 权限。
            </p>
          </div>
        </div>
      )}

      <section className="card h-full p-5 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30 xl:col-span-8 min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
              <TestTube2 size={16} /> 模型与接口
            </h3>
            <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
              这里配置平台默认模型。智能体可以在自己的编辑页覆盖默认 LLM。
            </p>
          </div>
          <button className="btn-secondary text-sm flex items-center gap-2 shrink-0" onClick={testConnection} disabled={testing}>
            <Server size={14} /> {testing ? '测试中...' : '测试服务连接'}
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="默认 LLM 模型" hint="影响未单独指定模型的智能体和平台任务。">
            <input
              className="input-field text-sm"
              value={local.llm_model || ''}
              disabled={disabled}
              onChange={e => setLocal({ ...local, llm_model: e.target.value })}
              onBlur={e => { if (e.target.value) save({ llm_model: e.target.value }, 'llm_model') }}
              placeholder="如：qwen-plus"
            />
          </Field>
          <ReadonlyItem label="Vision 模型" value={local.vision_model} />
          <ReadonlyItem label="Embedding 模型" value={local.embedding_model} />
          <ReadonlyItem label="Embedding 维度" value={local.embedding_dim} />
        </div>

        <div className="flex items-start gap-2 p-3 rounded-xl bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800/30">
          <AlertCircle size={14} className="text-rose-500 dark:text-rose-400 shrink-0 mt-0.5" />
          <p className="text-xs text-rose-700 dark:text-rose-300">
            Embedding 模型和维度会影响现有向量索引兼容性，当前仅展示运行配置，不在前端直接修改。
          </p>
        </div>
      </section>

      <section className="card h-full p-5 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30 xl:col-span-4 min-w-0">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
            <Sliders size={16} /> 平台默认处理
          </h3>
          <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
            这些是新上传任务的默认值。具体上传时可在知识库详情页按本次资料覆盖。
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {PROCESSING_DEFAULT_FIELDS.map(({ key, label, value }) => (
            <ReadonlyItem key={key} label={label} value={value(local[key])} />
          ))}
        </div>

        <div className="flex items-start gap-2 p-3 rounded-xl bg-sky-50 dark:bg-sky-900/30 border border-sky-200 dark:border-sky-800/30">
          <Info size={14} className="text-sky-500 dark:text-sky-400 shrink-0 mt-0.5" />
          <p className="text-xs text-sky-700 dark:text-sky-300">
            解析器、分块、实体抽取和多模态处理属于知识库入库策略，后续应主要在知识库详情和上传面板调整。
          </p>
        </div>
      </section>

      <section className="card h-full p-5 space-y-5 dark:bg-sky-900/20 dark:border-sky-800/30 xl:col-span-12 min-w-0">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
            <Search size={16} /> 检索调优
          </h3>
          <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
            调整 RRF 融合检索、BM25、向量和图谱通道参数。修改后对后续查询生效。
          </p>
        </div>

        <div className="space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="启用通道" hint="逗号分隔，可用 bm25、vector、graph。">
              <input
                className="input-field text-sm"
                value={rrf.enabled_channels || ''}
                disabled={disabled}
                onChange={e => setLocal({ ...local, rrf: { ...rrf, enabled_channels: e.target.value } })}
                onBlur={e => saveRrfField('enabled_channels', e.target.value)}
              />
            </Field>
            <Field label="BM25 分词器" hint="默认使用 jieba；仅影响后续检索任务。">
              <input
                className="input-field text-sm"
                value={rrf.bm25_tokenizer || ''}
                disabled={disabled}
                onChange={e => setLocal({ ...local, rrf: { ...rrf, bm25_tokenizer: e.target.value } })}
                onBlur={e => saveRrfField('bm25_tokenizer', e.target.value.trim() || RRF_DEFAULTS.bm25_tokenizer)}
              />
            </Field>
          </div>

          <div className="border-t border-cloud-200/80 dark:border-sky-800/30 pt-4">
            <p className="text-2xs font-medium text-ink-muted dark:text-cloud-500 mb-3">数值参数</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
              {RRF_NUMBER_FIELDS.map(([key, label, min, max, step]) => (
                <Field key={key} label={label}>
                  <input
                    className="input-field text-sm"
                    type="number"
                    min={min}
                    max={max}
                    step={step}
                    value={rrf[key] ?? ''}
                    disabled={disabled}
                    onChange={e => {
                      const value = step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value, 10)
                      setLocal({ ...local, rrf: { ...rrf, [key]: Number.isNaN(value) ? '' : value } })
                    }}
                    onBlur={e => {
                      const value = step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value, 10)
                      if (!Number.isNaN(value)) saveRrfField(key, value)
                    }}
                  />
                </Field>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="card h-full p-5 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30 xl:col-span-4 min-w-0">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
            <Gauge size={16} /> 运行限制
          </h3>
          <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
            控制平台级并发，避免上传和检索任务耗尽模型或服务器资源。
          </p>
        </div>

        <Field label="最大并发数" hint="后端会限制在 1-16 之间。">
          <div className="flex items-center gap-3">
            <input
              type="range"
              min="1"
              max="16"
              step="1"
              value={local.max_async || 4}
              disabled={disabled}
              onChange={e => setLocal({ ...local, max_async: parseInt(e.target.value, 10) })}
              onMouseUp={() => save({ max_async: parseInt(local.max_async, 10) }, 'max_async')}
              onTouchEnd={() => save({ max_async: parseInt(local.max_async, 10) }, 'max_async')}
              className="w-full accent-sky-500"
            />
            <span className="font-mono text-sky-500 dark:text-sky-400 font-medium w-10 text-right">{local.max_async || 4}</span>
          </div>
        </Field>
      </section>

      <section className="card h-full p-5 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30 xl:col-span-4 min-w-0">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
            <Database size={16} /> 存储与能力边界
          </h3>
          <p className="text-xs text-ink-muted dark:text-cloud-500 mt-1">
            这些来自服务端运行环境，前端先以只读方式展示，避免误改部署级配置。
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3">
          <ReadonlyItem label="知识库工作目录" value={local.working_dir} />
          <ReadonlyItem label="解析输出目录" value={local.parser_output_dir} />
          <ReadonlyItem label="支持文件格式" value={(local.supported_extensions || []).join(' ')} />
          <ReadonlyItem label="当前缓存策略" value="按知识库实例缓存，维护入口已移至监控页" />
        </div>
      </section>

      <section className="card h-full p-5 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30 xl:col-span-4 min-w-0">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300">
          <ShieldCheck size={16} /> 安全与权限
        </h3>
        <p className="text-xs text-ink-muted dark:text-cloud-500">
          用户、角色和权限矩阵归口在用户管理；审计事件归口在审计日志。平台设置只负责展示和修改系统级策略。
        </p>
        <div className="flex flex-wrap gap-2">
          <span className="tag tag-blue"><Route size={10} /> 用户管理处理 RBAC</span>
          <span className="tag tag-amber"><Cpu size={10} /> 监控页处理运行维护</span>
          <span className="tag tag-teal"><Save size={10} /> 修改会触发后端权限校验</span>
        </div>
      </section>
    </div>
  )
}
