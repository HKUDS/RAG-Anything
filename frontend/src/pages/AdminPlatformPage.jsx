import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, Save, ServerCog } from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../context/AuthContext'
import { platformReadOnlyState } from './preferencesPresentation'

const LIMITS = [
  ['worker_concurrency', 'Worker 并发上限', 1],
  ['provider_concurrency', 'Provider 并发上限', 1],
  ['personal_concurrency', '个人并发上限', 1],
  ['interactive_wait_seconds', '交互等待时间（秒）', 0],
  ['llm_timeout', 'LLM 等待时间（秒）', 1],
  ['cache_capacity', '缓存容量', 1],
  ['bm25_top_k', 'BM25 Top K 上限', 1],
  ['vector_top_k', '向量 Top K 上限', 1],
  ['graph_top_k', '图谱 Top K 上限', 1],
  ['graph_depth', '图谱深度上限', 0],
]

const DEFAULT_FIELDS = {
  ingestion: [
    ['parser', '默认解析器', 'text'], ['chunking_strategy', '默认分块策略', 'text'],
    ['chunk_size', '默认分块大小', 'number'], ['entity_types', '默认实体类型', 'list'],
    ['minimum_relation_degree', '默认最低关系度', 'number'],
    ['enable_image', '默认处理图片', 'boolean'], ['enable_table', '默认处理表格', 'boolean'],
    ['enable_equation', '默认处理公式', 'boolean'], ['enable_video', '默认处理视频', 'boolean'],
  ],
  retrieval: [
    ['preset', '默认检索预设', 'text'], ['rrf_k', '默认 RRF', 'number'],
    ['bm25_top_k', '默认 BM25 Top K', 'number'], ['vector_top_k', '默认向量 Top K', 'number'],
    ['graph_top_k', '默认图谱 Top K', 'number'], ['graph_depth', '默认图谱深度', 'number'],
    ['channels', '默认检索通道', 'list'], ['bm25_tokenizer', '默认 BM25 分词器', 'text'],
    ['bm25_k1', '默认 BM25 k1', 'number'], ['bm25_b', '默认 BM25 b', 'number'],
  ],
  runtime: [
    ['personal_concurrency', '默认个人并发', 'number'], ['llm_timeout', '默认 LLM 等待时间', 'number'],
  ],
}

const ALLOW_LISTS = [
  ['llm_profile_ids', '文本模型'],
  ['vlm_profile_ids', '图片理解模型'],
  ['embedding_profile_ids', '视觉向量模型'],
  ['parsers', '解析器'],
  ['chunking_strategies', '分块策略'],
  ['bm25_tokenizers', 'BM25 分词器'],
]

const emptyPolicy = () => ({ defaults: {}, allowed: {}, limits: {}, state: {} })

function normalizePolicy(settings) {
  const policy = settings || {}
  return {
    defaults: { ...(policy.defaults || {}) },
    allowed: { ...(policy.allowed || {}) },
    limits: { ...(policy.limits || {}) },
    state: { ...(policy.state || {}) },
  }
}

function listText(value) {
  return Array.isArray(value) ? value.join(', ') : ''
}

export default function AdminPlatformPage({ onToast }) {
  const { hasPermission } = useAuth()
  const [data, setData] = useState(null)
  const [draft, setDraft] = useState(emptyPolicy)
  const [profiles, setProfiles] = useState([])
  const [catalogError, setCatalogError] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    Promise.allSettled([api.getPlatformSettings(), api.listModelProfiles()]).then(([policy, catalog]) => {
      if (!active) return
      if (policy.status === 'fulfilled') {
        setData(policy.value)
        setDraft(normalizePolicy(policy.value.settings))
      } else {
        setError(policy.reason?.message || '平台策略加载失败')
      }
      if (catalog.status === 'fulfilled') setProfiles(catalog.value.profiles || [])
      else setCatalogError(catalog.reason?.message || '模型目录加载失败')
    })
    return () => { active = false }
  }, [])

  const deploymentReadOnly = Boolean(draft.state?.read_only)
  const canWrite = hasPermission('settings:write')
  const { readOnly, reason: readOnlyReason } = platformReadOnlyState(deploymentReadOnly, canWrite)
  const profileOptions = useMemo(() => ({
    llm: profiles.filter(item => item.kind === 'llm'),
    vlm: profiles.filter(item => item.kind === 'vlm'),
  }), [profiles])
  const setDraftPath = (group, field, value) => {
    setDraft(current => ({ ...current, [group]: { ...current[group], [field]: value } }))
  }
  const setDefaultField = (section, field, value) => {
    setDraft(current => ({
      ...current,
      defaults: {
        ...current.defaults,
        [section]: { ...(current.defaults?.[section] || {}), [field]: value },
      },
    }))
  }
  const save = async () => {
    if (!data || readOnly) return
    setSaving(true)
    setError('')
    try {
      const result = await api.updatePlatformSettings({ expected_revision: data.revision, settings: draft })
      setData(result)
      setDraft(normalizePolicy(result.settings))
      onToast?.('平台策略已保存', 'success')
    } catch (err) {
      setError(err.message || '平台策略保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (!data && !error) return <div className="py-20 text-center" role="status"><Loader2 className="mx-auto animate-spin text-sky-500" /><p className="mt-3 text-sm text-ink-muted">正在加载平台策略…</p></div>

  return <div className="mx-auto w-full max-w-5xl space-y-5">
    <header className="page-header page-header-divider">
      <div className="flex gap-3">
        <span className="rounded-lg bg-sky-50 p-2 text-sky-600 dark:bg-sky-500/10"><ServerCog size={20} /></span>
        <div><h1 className="page-title">平台管理</h1><p className="page-subtitle">维护可选模型、默认值和资源上限。部署连接、Host、Key 与环境变量不属于此页面。</p></div>
      </div>
      {data && <span className="badge badge-info">修订 {data.revision}</span>}
    </header>

    {error && <div role="alert" className="flex gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"><AlertCircle size={16} className="shrink-0" />{error}</div>}
    {catalogError && <div role="alert" className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><AlertCircle size={16} className="shrink-0" />{catalogError}；模型默认值暂不可编辑，其他策略仍可维护。</div>}
    {readOnly && <div role="status" className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><AlertCircle size={16} className="shrink-0" />{readOnlyReason === 'deployment' ? '此部署当前为只读状态；以下内容仅供审阅。' : '当前角色只有平台查看权限；编辑需要 settings:write 权限。'}</div>}

    <section className="card p-5 sm:p-6">
      <div><h2 className="text-base font-semibold text-ink-primary">平台默认模型</h2><p className="mt-1 text-sm text-ink-muted">用户未保存选择时使用。不可用模型会保留可见状态，无法被静默替换。</p></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {[['llm_profile_id', '默认文本模型', 'llm'], ['vlm_profile_id', '默认图片理解模型', 'vlm']].map(([field, label, kind]) => <label className="block text-sm font-medium" key={field}>{label}
          <select className="select-field mt-2" disabled={readOnly || Boolean(catalogError)} value={draft.defaults.models?.[field] || ''} onChange={event => setDraftPath('defaults', 'models', { ...(draft.defaults.models || {}), [field]: event.target.value })}>
            <option value="">继承部署默认</option>{profileOptions[kind].map(profile => <option value={profile.id} key={profile.id} disabled={!profile.available}>{profile.model || profile.display_name}</option>)}
          </select>
        </label>)}
      </div>
    </section>

    {Object.entries(DEFAULT_FIELDS).map(([section, fields]) => <section className="card p-5 sm:p-6" key={section}>
      <div><h2 className="text-base font-semibold text-ink-primary">{({ ingestion: '上传与解析默认值', retrieval: '检索默认值', runtime: '运行默认值' })[section]}</h2><p className="mt-1 text-sm text-ink-muted">用户未保存覆盖值时使用，仍受下方硬上限约束。</p></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map(([field, label, type]) => <label className="block text-sm font-medium" key={field}>{label}
          {type === 'boolean'
            ? <select className="select-field mt-2" disabled={readOnly} value={String(draft.defaults?.[section]?.[field] ?? false)} onChange={event => setDefaultField(section, field, event.target.value === 'true')}><option value="true">开启</option><option value="false">关闭</option></select>
            : <input className="input-field mt-2" disabled={readOnly} type={type === 'number' ? 'number' : 'text'} value={type === 'list' ? listText(draft.defaults?.[section]?.[field]) : (draft.defaults?.[section]?.[field] ?? '')} onChange={event => setDefaultField(section, field, type === 'list' ? event.target.value.split(',').map(value => value.trim()).filter(Boolean) : type === 'number' ? Number(event.target.value) : event.target.value)} />}
        </label>)}
      </div>
    </section>)}

    <section className="card p-5 sm:p-6">
      <div><h2 className="text-base font-semibold text-ink-primary">允许范围</h2><p className="mt-1 text-sm text-ink-muted">逗号分隔。留空表示不额外限制；保存前由服务端按目录和类型校验。</p></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {ALLOW_LISTS.map(([field, label]) => <label className="block text-sm font-medium" key={field}>{label}
          <input className="input-field mt-2" disabled={readOnly} value={listText(draft.allowed?.[field])} onChange={event => setDraftPath('allowed', field, event.target.value.split(',').map(value => value.trim()).filter(Boolean))} />
        </label>)}
      </div>
    </section>

    <section className="card p-5 sm:p-6">
      <div><h2 className="text-base font-semibold text-ink-primary">资源硬上限</h2><p className="mt-1 text-sm text-ink-muted">用户可保存自己的偏好，但实际执行值不会超过这些边界。</p></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {LIMITS.map(([field, label, min]) => <label className="block text-sm font-medium" key={field}>{label}
          <input className="input-field mt-2" type="number" min={min} disabled={readOnly} value={draft.limits?.[field] ?? ''} onChange={event => setDraftPath('limits', field, event.target.value === '' ? undefined : Number(event.target.value))} />
        </label>)}
      </div>
    </section>

    <section className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
      <div><h2 className="text-base font-semibold text-ink-primary">策略状态</h2><p className="mt-1 text-sm text-ink-muted">检索预设版本：{draft.state?.retrieval_preset_version || 'v1'}</p></div>
      <button className="btn-primary" onClick={save} disabled={!data || saving || readOnly} title={!canWrite ? '需要 settings:write 权限' : undefined}>{saving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}{saving ? '保存中…' : readOnly ? '只读模式' : '保存平台策略'}</button>
    </section>
  </div>
}
