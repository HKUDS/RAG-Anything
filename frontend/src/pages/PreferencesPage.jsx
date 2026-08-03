import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  BrainCircuit,
  Check,
  FileInput,
  Gauge,
  Laptop,
  Loader2,
  Moon,
  Palette,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  UserRound,
} from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../context/AuthContext'
import { boundedRange, findModelProfile, mergeSavedSectionDrafts, modelProfileSummary, modelSettingValueLabel, retrievalPresetValues, settingValueLabel } from './preferencesPresentation'

const SETTINGS_META = {
  models: { title: 'AI 模型', description: '为后续任务选择文本与图片理解模型。', icon: BrainCircuit },
  ingestion: { title: '上传与解析', description: '控制新任务的解析、分块和多模态处理方式。', icon: FileInput },
  retrieval: { title: '检索策略', description: '从常用方案开始，需要时再展开底层检索参数。', icon: Search },
  runtime: { title: '运行控制', description: '调整个人并发和等待时间，始终受平台上限保护。', icon: Gauge },
  appearance: { title: '外观', description: '选择适合当前设备和环境的显示模式。', icon: Palette },
  account: { title: '账户资料', description: '维护用户名，修改时需要验证当前密码。', icon: UserRound },
  security: { title: '密码与安全', description: '更新登录密码，不影响其他个人设置。', icon: ShieldCheck },
}

const SECTION_META = Object.fromEntries(
  Object.entries(SETTINGS_META).filter(([id]) => ['models', 'ingestion', 'retrieval', 'runtime'].includes(id)),
)

const SETTINGS_NAV = [
  { label: '智能与任务', items: ['models', 'ingestion', 'retrieval', 'runtime'] },
  { label: '账户与体验', items: ['appearance', 'account', 'security'] },
]

const SOURCE_LABELS = {
  platform_default: '平台默认',
  platform_limit: '平台限制',
  user_setting: '个人设置',
  resource_setting: '智能体或知识库设置',
  request_selection: '本次选择',
  index_compatibility: '索引兼容规则',
  legacy_environment: '部署兼容值',
  agent_setting: '智能体设置',
  kb_setting: '知识库设置',
  request_override: '本次选择',
}

const FIELD_LABELS = {
  parser: '解析器',
  chunking_strategy: '分块策略',
  chunk_size: '分块大小',
  entity_types: '实体类型',
  minimum_relation_degree: '最低关系度',
  enable_image: '图片处理',
  enable_table: '表格处理',
  enable_equation: '公式处理',
  enable_video: '视频处理',
  preset: '检索预设',
  rrf_k: 'RRF',
  bm25_top_k: 'BM25 Top K',
  vector_top_k: '向量 Top K',
  graph_top_k: '图谱 Top K',
  graph_depth: '图谱深度',
  channels: '检索通道',
  bm25_tokenizer: 'BM25 分词器',
  bm25_k1: 'BM25 k1',
  bm25_b: 'BM25 b',
  personal_concurrency: '个人并发额度',
  llm_timeout: 'LLM 等待时间',
}

function FieldState({ label, stored, effective, source, constraint, valueLabel = settingValueLabel }) {
  const sourceLabel = SOURCE_LABELS[source] || source || '平台默认'
  return <div className="preferences-field-state-item">
    {label && <p>{label}</p>}
    <dl className="preferences-field-state">
      <div><dt>已保存</dt><dd>{valueLabel(stored)}</dd></div>
      <div><dt>实际生效</dt><dd>{valueLabel(effective)}</dd></div>
      <div><dt>来源</dt><dd>{sourceLabel}</dd></div>
      {constraint && <div className="is-constrained"><dt>约束</dt><dd>{constraint.maximum !== undefined ? `平台上限 ${constraint.maximum}` : `平台要求 ${settingValueLabel(constraint.required)}`}</dd></div>}
    </dl>
  </div>
}

function SettingsBlock({ id, title, description, icon: Icon, children, error, dirty, actions }) {
  return <section id={id} className="preferences-section" aria-labelledby={`${id}-heading`}>
    <div className="preferences-section-intro">
      <span className="preferences-section-icon"><Icon size={18} aria-hidden="true" /></span>
      <div>
        <div className="preferences-section-title-row">
          <h2 id={`${id}-heading`}>{title}</h2>
          {dirty && <span className="preferences-unsaved">未保存</span>}
        </div>
        <p id={`${id}-hint`}>{description}</p>
      </div>
    </div>
    <div className="preferences-section-body">
      {error && <div id={`${id}-error`} role="alert" className="preferences-alert preferences-alert-error"><AlertCircle size={16} aria-hidden="true" />{error}</div>}
      {children}
      {actions && <div className="preferences-section-actions">{actions}</div>}
    </div>
  </section>
}

function Section({ id, title, description, icon, children, pending, error, onSave, onReset, dirty }) {
  const actions = <>
    <button type="button" className="btn-secondary text-xs" disabled={pending} onClick={onReset}><RotateCcw size={14} />恢复继承</button>
    <button type="button" className="btn-primary text-xs" disabled={pending || !dirty} onClick={onSave}>{pending ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}{pending ? '保存中' : '保存更改'}</button>
  </>
  return <SettingsBlock id={id} title={title} description={description} icon={icon} error={error} dirty={dirty} actions={actions}>{children}</SettingsBlock>
}

export default function PreferencesPage({ onToast }) {
  const { verifyToken } = useAuth()
  const contentRef = useRef(null)
  const [data, setData] = useState(null)
  const [options, setOptions] = useState(null)
  const [profiles, setProfiles] = useState([])
  const [drafts, setDrafts] = useState({})
  const [status, setStatus] = useState({})
  const [account, setAccount] = useState({ username: '', current_password: '' })
  const [password, setPassword] = useState({ old_password: '', new_password: '', confirm: '' })
  const [accountError, setAccountError] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [notice, setNotice] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('raganything_theme_mode') || localStorage.getItem('raganything_theme') || 'system')
  const [activeSection, setActiveSection] = useState(() => window.location.hash.slice(1) || 'models')

  const applyTheme = value => {
    const resolved = value === 'system'
      ? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : value
    localStorage.setItem('raganything_theme_mode', value)
    localStorage.setItem('raganything_theme', resolved)
    document.documentElement.classList.toggle('dark', resolved === 'dark')
    setTheme(value)
    window.dispatchEvent(new CustomEvent('raganything-theme-change', { detail: resolved }))
  }

  useEffect(() => {
    let active = true
    const loadSettings = async () => {
      try {
        const settings = await api.getPersonalSettings()
        if (!active) return
        setData(settings); setDrafts(settings.stored || {})
      } catch (error) {
        if (!active) return
        // Keep account, appearance, and security controls reachable even when
        // the settings service itself is unavailable.
        setData({ revision: 0, stored: {}, effective: {}, sources: {}, constraints: {} })
        setStatus(current => ({ ...current, global: error.message || '个人设置加载失败' }))
      }
    }
    const loadOptions = async () => {
      try { const value = await api.getPersonalSettingsOptions(); if (active) setOptions(value) }
      catch (error) { if (active) setStatus(current => ({ ...current, options: error.message || '模型选项暂不可用' })) }
    }
    const loadCatalog = async () => {
      try { const value = await api.listModelProfiles(); if (active) setProfiles(value?.profiles || []) }
      catch (error) { if (active) setStatus(current => ({ ...current, models: { error: error.message || '模型目录暂不可用' } })) }
    }
    const loadAccount = async () => {
      try {
        const value = await api.getMe?.()
        if (active && value) {
          setAccount(current => ({ ...current, username: value?.user?.username || '' }))
        }
      } catch (error) {
        if (active) setAccountError(error.message || '账户资料加载失败')
      }
    }
    void loadSettings(); void loadOptions(); void loadCatalog(); void loadAccount()
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!data || typeof IntersectionObserver === 'undefined') return undefined
    const sections = Object.keys(SETTINGS_META)
      .map(id => document.getElementById(id))
      .filter(Boolean)
    const observer = new IntersectionObserver(entries => {
      const visible = entries
        .filter(entry => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
      if (visible?.target?.id) setActiveSection(visible.target.id)
    }, { root: contentRef.current || document.querySelector('.cockpit-main'), rootMargin: '-16% 0px -68%', threshold: [0, 0.15, 0.4] })
    sections.forEach(section => observer.observe(section))
    return () => observer.disconnect()
  }, [data])

  const effective = data?.effective || {}
  const dirty = section => JSON.stringify(drafts[section] || {}) !== JSON.stringify(data?.stored?.[section] || {})
  const setDraft = (section, patch) => setDrafts(current => ({ ...current, [section]: { ...(current[section] || {}), ...patch } }))
  const saveSection = async section => {
    setStatus(current => ({ ...current, [section]: { pending: true, error: '' } }))
    try {
      const result = await api.patchPersonalSettings(section, { expected_revision: data.revision, values: drafts[section] || {} })
      setData(result)
      setDrafts(current => mergeSavedSectionDrafts(current, section, result.stored))
      setNotice(`${SECTION_META[section].title}已保存`); onToast?.(`${SECTION_META[section].title}已保存`, 'success')
    } catch (error) {
      setDrafts(current => mergeSavedSectionDrafts(current, section, data?.stored || {}))
      setStatus(current => ({ ...current, [section]: { error: error.message || '保存失败' } }))
      onToast?.(error.message || '保存失败', 'error')
    }
    finally { setStatus(current => ({ ...current, [section]: { ...current[section], pending: false } })) }
  }
  const resetSection = async section => {
    setStatus(current => ({ ...current, [section]: { pending: true, error: '' } }))
    try {
      const result = await api.patchPersonalSettings(section, { expected_revision: data.revision, values: null })
      setData(result)
      setDrafts(current => ({ ...current, [section]: {} }))
      setNotice(`${SECTION_META[section].title}已恢复继承`)
    }
    catch (error) { setStatus(current => ({ ...current, [section]: { error: error.message || '恢复继承失败' } })) }
    finally { setStatus(current => ({ ...current, [section]: { ...current[section], pending: false } })) }
  }
  const profileChoices = useMemo(
    () => options?.profiles?.length ? options.profiles : profiles,
    [options, profiles],
  )
  const profileFor = field => findModelProfile(profileChoices, drafts.models?.[field] ?? effective.models?.[field])
  const modelValueLabel = value => modelSettingValueLabel(profileChoices, value)
  const runtimeConcurrencyRange = boundedRange(options?.limits, 'personal_concurrency', 64)
  const runtimeTimeoutRange = boundedRange(options?.limits, 'llm_timeout', 600)
  const selectedRetrievalPreset = drafts.retrieval?.preset ?? effective.retrieval?.preset ?? 'balanced'
  const selectedPresetValues = retrievalPresetValues(selectedRetrievalPreset)
  if (!data) return <div className="py-20 text-center" role="status"><Loader2 className="mx-auto animate-spin text-sky-500" /><p className="mt-3 text-sm text-ink-muted">正在加载个人设置…</p>{status.global && <p role="alert" className="mt-3 text-rose-600">{status.global}</p>}</div>

  const navigateToSection = (event, id) => {
    setActiveSection(id)
    if (!window.matchMedia('(min-width: 1101px)').matches) return
    event.preventDefault()
    window.history.replaceState(null, '', `#${id}`)
    const target = document.getElementById(id)
    const scrollContainer = contentRef.current
    if (!target || !scrollContainer) return
    scrollContainer.scrollTo({
      top: target.offsetTop,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    })
  }

  const sectionProps = section => ({ id: section, ...SECTION_META[section], pending: status[section]?.pending, error: status[section]?.error, dirty: dirty(section), onSave: () => saveSection(section), onReset: () => resetSection(section) })
  return <div className="preferences-page">
    <nav className="preferences-mobile-nav" aria-label="个人设置分区">
      {Object.entries(SETTINGS_META).map(([id, { title, icon: Icon }]) => <a className={activeSection === id ? 'is-active' : ''} href={`#${id}`} aria-current={activeSection === id ? 'location' : undefined} onClick={event => navigateToSection(event, id)} key={id}><Icon size={15} aria-hidden="true" /><span>{title}</span></a>)}
    </nav>
    <div className="preferences-shell">
      <aside className="preferences-sidebar">
        <div className="preferences-sidebar-heading">
          <span><SlidersHorizontal size={18} aria-hidden="true" /></span>
          <div><strong>设置中心</strong><small>修订 {data.revision}</small></div>
        </div>
        <nav aria-label="个人设置分区">
          {SETTINGS_NAV.map(group => <div className="preferences-nav-group" key={group.label}>
            <p>{group.label}</p>
            {group.items.map(id => {
              const { title, icon: Icon } = SETTINGS_META[id]
              return <a className={activeSection === id ? 'is-active' : ''} href={`#${id}`} aria-current={activeSection === id ? 'location' : undefined} onClick={event => navigateToSection(event, id)} key={id}><Icon size={16} aria-hidden="true" /><span>{title}</span></a>
            })}
          </div>)}
        </nav>
        <p className="preferences-sidebar-note">每个分区独立保存。平台限制始终优先。</p>
      </aside>
      <div className="preferences-content" ref={contentRef}>
        <div className="preferences-context">
          <span><Check size={16} aria-hidden="true" /></span>
          <div><strong>设置只对当前账户生效</strong><p>模型、上传和检索设置会从下一次新任务开始使用。</p></div>
        </div>
        <p className="sr-only" role="status" aria-live="polite">{notice}</p>
        {(status.global || status.options) && <div role="alert" className="preferences-alert preferences-alert-warning"><AlertCircle size={16} aria-hidden="true" /><span>{status.global || status.options}；账户、主题与密码功能仍可正常使用。</span></div>}
        <Section {...sectionProps('models')}>
          <div className="preferences-model-grid">
            {[['llm_profile_id', '文本模型', 'llm'], ['vlm_profile_id', '图片理解模型', 'vlm']].map(([field, label, kind]) => {
              const profile = profileFor(field)
              const summary = modelProfileSummary(profile)
              return <div key={field} className="preferences-model-field">
                <label htmlFor={`models-${field}`}>
                  <span>{label}</span>
                  <select
                    id={`models-${field}`}
                    aria-describedby={`models-hint ${field}-model-detail${status.models?.error ? ' models-error' : ''}`}
                    aria-invalid={Boolean(status.models?.error)}
                    className="select-field"
                    value={drafts.models?.[field] ?? effective.models?.[field] ?? ''}
                    onChange={event => setDraft('models', { [field]: event.target.value })}
                  >
                    <option value="">继承平台默认</option>
                    {profileChoices.filter(item => item.kind === kind).map(item => <option key={item.id} value={item.id} disabled={!item.available}>{item.model || item.display_name}</option>)}
                  </select>
                </label>
                <div id={`${field}-model-detail`} className="preferences-model-summary">
                  <div><span className={profile?.available === false ? 'is-unavailable' : 'is-available'}>{summary.status}</span><code>{profile?.model || '平台默认'}</code></div>
                  {summary.technical && <details>
                    <summary>查看技术信息</summary>
                    <dl>
                      <div><dt>配置 ID</dt><dd>{summary.technical.id}</dd></div>
                      <div><dt>适配器</dt><dd>{summary.technical.provider}</dd></div>
                      {summary.technical.capabilities.length > 0 && <div><dt>能力</dt><dd>{summary.technical.capabilities.join('、')}</dd></div>}
                    </dl>
                  </details>}
                </div>
                <FieldState label={`${label}状态`} stored={data.stored?.models?.[field]} effective={effective.models?.[field]} source={data.sources?.models?.[field]} constraint={data.constraints?.models?.[field]} valueLabel={modelValueLabel} />
              </div>
            })}
          </div>
        </Section>

        <Section {...sectionProps('ingestion')}>
          <div className="preferences-field-grid">
            <label htmlFor="ingestion-parser">解析器<select id="ingestion-parser" className="select-field" value={drafts.ingestion?.parser ?? effective.ingestion?.parser ?? 'docling'} onChange={event => setDraft('ingestion', { parser: event.target.value })}>{(options?.allowed?.parsers || ['docling']).map(value => <option value={value} key={value}>{value}</option>)}</select></label>
            <label htmlFor="ingestion-strategy">分块策略<select id="ingestion-strategy" className="select-field" value={drafts.ingestion?.chunking_strategy ?? effective.ingestion?.chunking_strategy ?? 'recursive'} onChange={event => setDraft('ingestion', { chunking_strategy: event.target.value })}><option value="recursive">递归分块</option><option value="fixed">固定长度</option></select></label>
            <label htmlFor="ingestion-size">分块大小<input id="ingestion-size" className="input-field" type="number" min="64" value={drafts.ingestion?.chunk_size ?? effective.ingestion?.chunk_size ?? 800} onChange={event => setDraft('ingestion', { chunk_size: Number(event.target.value) })} /></label>
            <label htmlFor="ingestion-entities">实体类型<input id="ingestion-entities" className="input-field" value={(drafts.ingestion?.entity_types ?? effective.ingestion?.entity_types ?? []).join(', ')} placeholder="人物, 组织, 概念" onChange={event => setDraft('ingestion', { entity_types: event.target.value.split(',').map(value => value.trim()).filter(Boolean) })} /><small>使用逗号分隔，留空表示不额外限定。</small></label>
            <label htmlFor="ingestion-relation-degree">最低关系度<input id="ingestion-relation-degree" className="input-field" type="number" min="0" value={drafts.ingestion?.minimum_relation_degree ?? effective.ingestion?.minimum_relation_degree ?? 0} onChange={event => setDraft('ingestion', { minimum_relation_degree: Number(event.target.value) })} /></label>
          </div>
          <fieldset className="preferences-toggle-list">
            <legend>多模态内容处理</legend>
            {[['enable_image', '图片'], ['enable_table', '表格'], ['enable_equation', '公式'], ['enable_video', '视频']].map(([field, label]) => <label key={field}><span>{label}处理</span><input type="checkbox" checked={drafts.ingestion?.[field] ?? effective.ingestion?.[field] ?? false} onChange={event => setDraft('ingestion', { [field]: event.target.checked })} /></label>)}
          </fieldset>
          <details className="preferences-state-details">
            <summary>查看已保存值与生效状态</summary>
            <div className="preferences-state-grid">
              {['parser', 'chunking_strategy', 'chunk_size', 'entity_types', 'minimum_relation_degree', 'enable_image', 'enable_table', 'enable_equation', 'enable_video'].map(field => <FieldState key={field} label={FIELD_LABELS[field]} stored={data.stored?.ingestion?.[field]} effective={effective.ingestion?.[field]} source={data.sources?.ingestion?.[field]} constraint={data.constraints?.ingestion?.[field]} />)}
            </div>
          </details>
        </Section>

        <Section {...sectionProps('retrieval')}>
          <fieldset className="preferences-segmented">
            <legend className="sr-only">检索预设</legend>
            {['balanced', 'precise', 'broad', 'custom'].map(preset => <label key={preset}><input type="radio" name="retrieval-preset" value={preset} checked={selectedRetrievalPreset === preset} onChange={() => setDraft('retrieval', { preset, ...(retrievalPresetValues(preset) || {}) })} /><span>{({ balanced: '均衡', precise: '精准', broad: '广泛', custom: '自定义' })[preset]}</span></label>)}
          </fieldset>
          {selectedPresetValues && <div className="preferences-preset-preview" role="status" aria-live="polite">
            <strong>当前预设将保存以下检索范围</strong>
            <span>BM25 {selectedPresetValues.bm25_top_k} · 向量 {selectedPresetValues.vector_top_k} · 图谱 {selectedPresetValues.graph_top_k} · 深度 {selectedPresetValues.graph_depth}</span>
            <span>通道：{selectedPresetValues.channels.join(' / ')} · RRF {selectedPresetValues.rrf_k}</span>
          </div>}
          {selectedRetrievalPreset === 'custom' && <div className="preferences-advanced">
            <div className="preferences-field-grid three-columns">
              {[['rrf_k', 'RRF'], ['bm25_top_k', 'BM25 Top K'], ['vector_top_k', '向量 Top K'], ['graph_top_k', '图谱 Top K'], ['graph_depth', '图谱深度']].map(([field, label]) => <label key={field}>{label}<input className="input-field" type="number" min="0" value={drafts.retrieval?.[field] ?? effective.retrieval?.[field] ?? 0} onChange={event => setDraft('retrieval', { [field]: Number(event.target.value) })} /></label>)}
            </div>
            <fieldset className="preferences-subsection">
              <legend>通道与 BM25</legend>
              <div className="preferences-field-grid three-columns">
                <label>分词器<select className="select-field" value={drafts.retrieval?.bm25_tokenizer ?? effective.retrieval?.bm25_tokenizer ?? 'jieba'} onChange={event => setDraft('retrieval', { bm25_tokenizer: event.target.value })}>{(options?.allowed?.bm25_tokenizers || ['jieba']).map(value => <option value={value} key={value}>{value}</option>)}</select></label>
                {[['bm25_k1', 'BM25 k1', 0, 10, 0.1], ['bm25_b', 'BM25 b', 0, 1, 0.05]].map(([field, label, min, max, step]) => <label key={field}>{label}<input className="input-field" type="number" min={min} max={max} step={step} value={drafts.retrieval?.[field] ?? effective.retrieval?.[field] ?? 0} onChange={event => setDraft('retrieval', { [field]: Number(event.target.value) })} /></label>)}
              </div>
              <div className="preferences-channel-list"><span>检索通道</span>{[['bm25', 'BM25'], ['vector', '向量'], ['graph', '图谱']].map(([value, label]) => { const channels = drafts.retrieval?.channels ?? effective.retrieval?.channels ?? []; return <label key={value}><input type="checkbox" checked={channels.includes(value)} onChange={event => setDraft('retrieval', { channels: event.target.checked ? [...channels, value] : channels.filter(item => item !== value) })} />{label}</label> })}</div>
            </fieldset>
          </div>}
          <details className="preferences-state-details">
            <summary>查看已保存值与生效状态</summary>
            <div className="preferences-state-grid">
              {['preset', 'rrf_k', 'bm25_top_k', 'vector_top_k', 'graph_top_k', 'graph_depth', 'channels', 'bm25_tokenizer', 'bm25_k1', 'bm25_b'].map(field => <FieldState key={field} label={FIELD_LABELS[field]} stored={data.stored?.retrieval?.[field]} effective={effective.retrieval?.[field]} source={data.sources?.retrieval?.[field]} constraint={data.constraints?.retrieval?.[field]} />)}
            </div>
          </details>
        </Section>

        <Section {...sectionProps('runtime')}>
          <div className="preferences-range-grid">
            <label htmlFor="runtime-concurrency">个人并发额度<span>平台上限 {runtimeConcurrencyRange.max}</span><div><input id="runtime-concurrency" aria-describedby="runtime-hint" aria-valuetext={`${drafts.runtime?.personal_concurrency ?? effective.runtime?.personal_concurrency ?? 7} 个并发任务`} type="range" min={runtimeConcurrencyRange.min} max={runtimeConcurrencyRange.max} step="1" value={drafts.runtime?.personal_concurrency ?? effective.runtime?.personal_concurrency ?? 7} onInput={event => setDraft('runtime', { personal_concurrency: Number(event.currentTarget.value) })} onChange={event => setDraft('runtime', { personal_concurrency: Number(event.target.value) })} /><output htmlFor="runtime-concurrency">{drafts.runtime?.personal_concurrency ?? effective.runtime?.personal_concurrency ?? 7}</output></div><FieldState stored={data.stored?.runtime?.personal_concurrency} effective={effective.runtime?.personal_concurrency} source={data.sources?.runtime?.personal_concurrency} constraint={data.constraints?.runtime?.personal_concurrency} /></label>
            <label htmlFor="runtime-timeout">LLM 等待时间<span>平台上限 {runtimeTimeoutRange.max} 秒</span><div><input id="runtime-timeout" aria-describedby="runtime-hint" aria-valuetext={`${drafts.runtime?.llm_timeout ?? effective.runtime?.llm_timeout ?? 180} 秒`} type="range" min={runtimeTimeoutRange.min} max={runtimeTimeoutRange.max} step="5" value={drafts.runtime?.llm_timeout ?? effective.runtime?.llm_timeout ?? 180} onInput={event => setDraft('runtime', { llm_timeout: Number(event.currentTarget.value) })} onChange={event => setDraft('runtime', { llm_timeout: Number(event.target.value) })} /><output htmlFor="runtime-timeout">{drafts.runtime?.llm_timeout ?? effective.runtime?.llm_timeout ?? 180}<small>秒</small></output></div><FieldState stored={data.stored?.runtime?.llm_timeout} effective={effective.runtime?.llm_timeout} source={data.sources?.runtime?.llm_timeout} constraint={data.constraints?.runtime?.llm_timeout} /></label>
          </div>
        </Section>

        <SettingsBlock {...SETTINGS_META.appearance} id="appearance">
          <fieldset className="preferences-theme-options">
            <legend className="sr-only">外观模式</legend>
            {[['system', '跟随系统', Laptop, '自动适应设备设置'], ['light', '浅色', Sun, '明亮清晰的界面'], ['dark', '深色', Moon, '减少暗处视觉刺激']].map(([value, label, Icon, helper]) => <label key={value}><input type="radio" name="theme" value={value} checked={theme === value} onChange={() => applyTheme(value)} /><span><Icon size={18} aria-hidden="true" /><strong>{label}</strong><small>{helper}</small></span></label>)}
          </fieldset>
          <p className="preferences-local-note">外观保存在当前浏览器，不影响其他用户。</p>
        </SettingsBlock>

        <SettingsBlock
          {...SETTINGS_META.account}
          id="account"
          error={accountError}
          actions={<button type="button" className="btn-primary text-xs" onClick={async () => { try { await api.updateMyProfile(account); await verifyToken(); setAccountError(''); setNotice('账户资料已更新'); onToast?.('资料已更新', 'success') } catch (error) { setAccountError(error.message || '资料更新失败') } }}><Save size={14} />保存资料</button>}
        >
          <div className="preferences-field-grid">
            <label htmlFor="account-username">用户名<input id="account-username" name="username" autoComplete="username" className="input-field" value={account.username} onChange={event => setAccount({ ...account, username: event.target.value })} /></label>
          </div>
          <label className="preferences-password-field" htmlFor="account-password">当前密码<input id="account-password" name="current-password" autoComplete="current-password" aria-invalid={Boolean(accountError)} aria-describedby={accountError ? 'account-error' : 'account-hint'} className="input-field" type="password" value={account.current_password} onChange={event => setAccount({ ...account, current_password: event.target.value })} /></label>
        </SettingsBlock>

        <SettingsBlock
          {...SETTINGS_META.security}
          id="security"
          error={passwordError}
          actions={<button type="button" className="btn-primary text-xs" onClick={async () => { if (password.new_password !== password.confirm) { setPasswordError('两次新密码输入不一致'); return } try { await api.updateMyPassword({ old_password: password.old_password, new_password: password.new_password }); setPassword({ old_password: '', new_password: '', confirm: '' }); setPasswordError(''); setNotice('密码已更新'); onToast?.('密码已更新', 'success') } catch (error) { setPasswordError(error.message || '密码更新失败') } }}><ShieldCheck size={14} />更新密码</button>}
        >
          <div className="preferences-field-grid three-columns">
            {[['old_password', '当前密码', 'current-password'], ['new_password', '新密码', 'new-password'], ['confirm', '确认新密码', 'new-password']].map(([field, label, autocomplete]) => <label key={field} htmlFor={`security-${field}`}>{label}<input id={`security-${field}`} name={field} autoComplete={autocomplete} aria-invalid={Boolean(passwordError)} aria-describedby={`security-hint${passwordError ? ' security-error' : ''}`} className="input-field" type="password" value={password[field]} onChange={event => setPassword({ ...password, [field]: event.target.value })} /></label>)}
          </div>
          <p className="preferences-local-note">密码提交成功后会立即清空。</p>
        </SettingsBlock>
      </div>
    </div>
  </div>
}
