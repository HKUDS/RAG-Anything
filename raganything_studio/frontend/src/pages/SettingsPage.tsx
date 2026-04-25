import { FormEvent, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2, ChevronDown, KeyRound, Loader2, RefreshCw,
  RotateCcw, Save, ScanSearch, ServerCog, XCircle, Zap,
} from 'lucide-react'
import { getEnvironment, getStudioSettings, listModels, testConnection, updateStudioSettings } from '../api/client'
import type { ConnectionTestKind, ConnectionTestResponse, ModelInfo, StudioSettings, StudioSettingsUpdate } from '../types/studio'

// ── known providers with preconfigured base URLs ──────────────────────────────

interface ProviderMeta {
  label: string
  baseUrl: string
  supportsModelList: boolean
}

const KNOWN_PROVIDERS: Record<string, ProviderMeta> = {
  'openai': { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', supportsModelList: true },
  'siliconflow': { label: '硅基流动 (SiliconFlow)', baseUrl: 'https://api.siliconflow.cn/v1', supportsModelList: true },
  'aliyun-bailian': { label: '阿里云百炼', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', supportsModelList: true },
  'baidu-qianfan': { label: '百度千帆', baseUrl: 'https://qianfan.baidubce.com/v2', supportsModelList: true },
  'volcengine': { label: '火山引擎', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', supportsModelList: true },
  'openrouter': { label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', supportsModelList: true },
  'deepseek': { label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', supportsModelList: true },
  'zhipu': { label: '智谱 AI (Zhipu)', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', supportsModelList: true },
  'moonshot': { label: '月之暗面 (Moonshot)', baseUrl: 'https://api.moonshot.cn/v1', supportsModelList: true },
  'groq': { label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1', supportsModelList: true },
  'together': { label: 'Together AI', baseUrl: 'https://api.together.xyz/v1', supportsModelList: true },
  'mistral': { label: 'Mistral AI', baseUrl: 'https://api.mistral.ai/v1', supportsModelList: true },
  'ollama': { label: 'Ollama', baseUrl: 'http://localhost:11434/v1', supportsModelList: true },
  'lmstudio': { label: 'LM Studio', baseUrl: 'http://localhost:1234/v1', supportsModelList: true },
  'vllm': { label: 'vLLM', baseUrl: 'http://localhost:8000/v1', supportsModelList: true },
  'openai-compatible': { label: 'OpenAI Compatible', baseUrl: '', supportsModelList: true },
  'custom': { label: 'Custom', baseUrl: '', supportsModelList: false },
}

// ── form state ────────────────────────────────────────────────────────────────

interface SettingsForm extends StudioSettingsUpdate {
  llm_api_key: string
  embedding_api_key: string
  vision_api_key: string
}

function makeForm(settings: StudioSettings): SettingsForm {
  return {
    data_dir: settings.data_dir,
    upload_dir: settings.upload_dir,
    working_dir: settings.working_dir,
    output_dir: settings.output_dir,
    llm_provider: settings.llm_provider,
    llm_model: settings.llm_model,
    llm_base_url: settings.llm_base_url ?? '',
    llm_api_key: '',
    embedding_provider: settings.embedding_provider,
    embedding_model: settings.embedding_model,
    embedding_dim: settings.embedding_dim,
    embedding_max_token_size: settings.embedding_max_token_size,
    embedding_base_url: settings.embedding_base_url ?? '',
    embedding_api_key: '',
    vision_provider: settings.vision_provider,
    vision_model: settings.vision_model,
    vision_base_url: settings.vision_base_url ?? '',
    vision_api_key: '',
    default_parser: settings.default_parser,
    default_parse_method: settings.default_parse_method,
    default_language: settings.default_language,
    default_device: settings.default_device,
  }
}

// ── test state ────────────────────────────────────────────────────────────────

interface TestState {
  status: 'idle' | 'pending' | 'ok' | 'error'
  latency?: number | null
  error?: string | null
  detected_dim?: number | null
}

const idleTest: TestState = { status: 'idle' }

// ── model picker state ────────────────────────────────────────────────────────

interface ModelPickerState {
  status: 'idle' | 'loading' | 'loaded' | 'error'
  models: ModelInfo[]
  error?: string | null
}

const idlePicker: ModelPickerState = { status: 'idle', models: [] }

// ── page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [activePanel, setActivePanel] = useState<'models' | 'runtime' | 'defaults'>('models')
  const [form, setForm] = useState<SettingsForm | null>(null)
  const [tests, setTests] = useState<Record<ConnectionTestKind, TestState>>({
    llm: idleTest, embedding: idleTest, vision: idleTest,
  })
  const [pickers, setPickers] = useState<Record<ConnectionTestKind, ModelPickerState>>({
    llm: idlePicker, embedding: idlePicker, vision: idlePicker,
  })

  const { data: environment } = useQuery({ queryKey: ['environment'], queryFn: getEnvironment })
  const { data: settings, error } = useQuery({ queryKey: ['settings'], queryFn: getStudioSettings })

  useEffect(() => {
    if (settings) setForm(makeForm(settings))
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!form) throw new Error('Settings are not loaded')
      return updateStudioSettings(toPayload(form))
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated)
      setForm(makeForm(updated))
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  function updateField<K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current))
  }

  function setTestState(kind: ConnectionTestKind, state: TestState) {
    setTests((prev) => ({ ...prev, [kind]: state }))
  }

  function setPickerState(kind: ConnectionTestKind, state: ModelPickerState) {
    setPickers((prev) => ({ ...prev, [kind]: state }))
  }

  // When a known provider is selected, auto-fill its base URL
  function handleProviderChange(kind: ConnectionTestKind, value: string) {
    const providerKey = `${kind}_provider` as keyof SettingsForm
    const baseUrlKey = `${kind}_base_url` as keyof SettingsForm
    updateField(providerKey, value)

    const meta = KNOWN_PROVIDERS[value]
    if (meta?.baseUrl) {
      updateField(baseUrlKey, meta.baseUrl)
    }
    // Reset picker when provider changes
    setPickerState(kind, idlePicker)
  }

  async function handleLoadModels(kind: ConnectionTestKind) {
    if (!form) return
    setPickerState(kind, { status: 'loading', models: [] })

    const provider = kind === 'llm' ? form.llm_provider
      : kind === 'embedding' ? form.embedding_provider
      : form.vision_provider
    const baseUrl = kind === 'llm' ? form.llm_base_url
      : kind === 'embedding' ? form.embedding_base_url
      : form.vision_base_url
    const apiKey = kind === 'llm' ? form.llm_api_key
      : kind === 'embedding' ? form.embedding_api_key
      : form.vision_api_key

    try {
      const result = await listModels({
        provider,
        base_url: baseUrl || null,
        api_key: apiKey || null,
      })
      if (result.ok) {
        setPickerState(kind, { status: 'loaded', models: result.models })
      } else {
        setPickerState(kind, { status: 'error', models: [], error: result.error ?? 'Failed to load models' })
      }
    } catch (err) {
      setPickerState(kind, {
        status: 'error', models: [],
        error: err instanceof Error ? err.message : String(err),
      })
    }
  }

  async function handleTest(kind: ConnectionTestKind) {
    if (!form) return
    setTestState(kind, { status: 'pending' })

    const payload = {
      kind,
      provider: kind === 'llm' ? form.llm_provider : kind === 'embedding' ? form.embedding_provider : form.vision_provider,
      model: kind === 'llm' ? form.llm_model : kind === 'embedding' ? form.embedding_model : form.vision_model,
      base_url: (kind === 'llm' ? form.llm_base_url : kind === 'embedding' ? form.embedding_base_url : form.vision_base_url) || null,
      api_key: (kind === 'llm' ? form.llm_api_key : kind === 'embedding' ? form.embedding_api_key : form.vision_api_key) || null,
      ...(kind === 'embedding' ? { embedding_dim: form.embedding_dim, embedding_max_token_size: form.embedding_max_token_size } : {}),
    }

    try {
      const result: ConnectionTestResponse = await testConnection(payload)
      if (result.ok) {
        setTestState(kind, { status: 'ok', latency: result.latency_ms, detected_dim: result.detected_dim })
        if (kind === 'embedding' && result.detected_dim != null) {
          updateField('embedding_dim', result.detected_dim)
        }
      } else {
        setTestState(kind, { status: 'error', error: result.error ?? 'Connection failed' })
      }
    } catch (err) {
      setTestState(kind, { status: 'error', error: err instanceof Error ? err.message : String(err) })
    }
  }

  const envRows = environment
    ? [
        ['Python', environment.python],
        ['RAG-Anything', environment.raganything_installed ? 'available' : 'missing'],
        ['LightRAG', environment.lightrag_installed ? 'available' : 'missing'],
        ['MinerU', environment.mineru_available ? 'available' : 'missing'],
        ['LibreOffice', environment.libreoffice_available ? 'available' : 'missing'],
        ['CUDA', environment.cuda_available ? 'available' : 'missing'],
      ]
    : []

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveMutation.mutate()
  }

  if (error) {
    return <section className="page"><div className="error-panel">{(error as Error).message}</div></section>
  }

  if (!form || !settings) {
    return <section className="page"><div className="empty">Loading settings…</div></section>
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Model providers, credentials, directories, and processing defaults</p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={() => setForm(makeForm(settings))}>
            <RotateCcw size={16} /> Reset
          </button>
          <button className="button primary" form="studio-settings-form" disabled={saveMutation.isPending}>
            <Save size={16} />
            {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>

      <div className="settings-layout">
        <aside className="settings-nav">
          <button className={activePanel === 'models' ? 'active' : ''} onClick={() => setActivePanel('models')}>
            <KeyRound size={16} /> Models
          </button>
          <button className={activePanel === 'runtime' ? 'active' : ''} onClick={() => setActivePanel('runtime')}>
            <ServerCog size={16} /> Runtime
          </button>
          <button className={activePanel === 'defaults' ? 'active' : ''} onClick={() => setActivePanel('defaults')}>
            <CheckCircle2 size={16} /> Defaults
          </button>
        </aside>

        <form className="settings-content" id="studio-settings-form" onSubmit={handleSubmit}>
          {activePanel === 'models' && (
            <div className="provider-grid">
              <ProviderSection
                title="LLM" kind="llm"
                provider={form.llm_provider} model={form.llm_model}
                baseUrl={form.llm_base_url ?? ''} apiKey={form.llm_api_key}
                configured={settings.llm_api_key_configured}
                testState={tests.llm} pickerState={pickers.llm}
                onProvider={(v) => handleProviderChange('llm', v)}
                onModel={(v) => updateField('llm_model', v)}
                onBaseUrl={(v) => updateField('llm_base_url', v)}
                onApiKey={(v) => updateField('llm_api_key', v)}
                onTest={() => handleTest('llm')}
                onLoadModels={() => handleLoadModels('llm')}
              />
              <ProviderSection
                title="Embedding" kind="embedding"
                provider={form.embedding_provider} model={form.embedding_model}
                baseUrl={form.embedding_base_url ?? ''} apiKey={form.embedding_api_key}
                configured={settings.embedding_api_key_configured}
                testState={tests.embedding} pickerState={pickers.embedding}
                onProvider={(v) => handleProviderChange('embedding', v)}
                onModel={(v) => updateField('embedding_model', v)}
                onBaseUrl={(v) => updateField('embedding_base_url', v)}
                onApiKey={(v) => updateField('embedding_api_key', v)}
                onTest={() => handleTest('embedding')}
                onLoadModels={() => handleLoadModels('embedding')}
              >
                <div className="dim-row">
                  <label style={{ flex: 1 }}>
                    Dimension
                    <input min={1} type="number" value={form.embedding_dim}
                      onChange={(e) => updateField('embedding_dim', Number(e.target.value))} />
                  </label>
                  {tests.embedding.status === 'ok' && tests.embedding.detected_dim != null && (
                    <span className="dim-detected">
                      <ScanSearch size={13} /> Auto-detected: {tests.embedding.detected_dim}
                    </span>
                  )}
                </div>
                <label>
                  Max tokens
                  <input min={1} type="number" value={form.embedding_max_token_size}
                    onChange={(e) => updateField('embedding_max_token_size', Number(e.target.value))} />
                </label>
              </ProviderSection>
              <ProviderSection
                title="Vision" kind="vision"
                provider={form.vision_provider} model={form.vision_model}
                baseUrl={form.vision_base_url ?? ''} apiKey={form.vision_api_key}
                configured={settings.vision_api_key_configured}
                testState={tests.vision} pickerState={pickers.vision}
                onProvider={(v) => handleProviderChange('vision', v)}
                onModel={(v) => updateField('vision_model', v)}
                onBaseUrl={(v) => updateField('vision_base_url', v)}
                onApiKey={(v) => updateField('vision_api_key', v)}
                onTest={() => handleTest('vision')}
                onLoadModels={() => handleLoadModels('vision')}
              />
            </div>
          )}

          {activePanel === 'runtime' && (
            <div className="split">
              <div className="panel stack">
                <h2>Directories</h2>
                <label>Data directory<input value={form.data_dir ?? ''} onChange={(e) => updateField('data_dir', e.target.value)} /></label>
                <label>Upload directory<input value={form.upload_dir ?? ''} onChange={(e) => updateField('upload_dir', e.target.value)} /></label>
                <label>Working directory<input value={form.working_dir ?? ''} onChange={(e) => updateField('working_dir', e.target.value)} /></label>
                <label>Output directory<input value={form.output_dir ?? ''} onChange={(e) => updateField('output_dir', e.target.value)} /></label>
                <label>Settings file<input value={settings.settings_file} readOnly /></label>
              </div>
              <div className="panel stack">
                <h2>Environment</h2>
                {envRows.map(([label, value]) => (
                  <div className="setting-row" key={label}>
                    <span>{label}</span>
                    <strong className={value === 'missing' ? 'env-missing' : ''}>{value}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activePanel === 'defaults' && (
            <div className="panel stack compact-settings">
              <h2>Processing Defaults</h2>
              <div className="form-grid">
                <label>
                  Parser
                  <select value={form.default_parser} onChange={(e) => updateField('default_parser', e.target.value)}>
                    <option value="mineru">mineru</option>
                    <option value="docling">docling</option>
                    <option value="paddleocr">paddleocr</option>
                  </select>
                </label>
                <label>
                  Parse method
                  <select value={form.default_parse_method} onChange={(e) => updateField('default_parse_method', e.target.value)}>
                    <option value="auto">auto</option>
                    <option value="ocr">ocr</option>
                    <option value="txt">txt</option>
                  </select>
                </label>
                <label>
                  Language
                  <select value={form.default_language} onChange={(e) => updateField('default_language', e.target.value)}>
                    <option value="ch">ch</option>
                    <option value="en">en</option>
                  </select>
                </label>
                <label>
                  Device
                  <select value={form.default_device} onChange={(e) => updateField('default_device', e.target.value)}>
                    <option value="cpu">cpu</option>
                    <option value="cuda">cuda</option>
                    <option value="cuda:0">cuda:0</option>
                    <option value="mps">mps</option>
                  </select>
                </label>
              </div>
            </div>
          )}

          {saveMutation.error ? <div className="error-panel">{saveMutation.error.message}</div> : null}
          {saveMutation.isSuccess ? <div className="success-panel">Settings saved</div> : null}
        </form>
      </div>
    </section>
  )
}

// ── ProviderSection ───────────────────────────────────────────────────────────

interface ProviderSectionProps {
  title: string
  kind: ConnectionTestKind
  provider: string
  model: string
  baseUrl: string
  apiKey: string
  configured: boolean
  testState: TestState
  pickerState: ModelPickerState
  onProvider: (v: string) => void
  onModel: (v: string) => void
  onBaseUrl: (v: string) => void
  onApiKey: (v: string) => void
  onTest: () => void
  onLoadModels: () => void
  children?: ReactNode
}

function ProviderSection({
  title, kind, provider, model, baseUrl, apiKey, configured,
  testState, pickerState, onProvider, onModel, onBaseUrl, onApiKey,
  onTest, onLoadModels, children,
}: ProviderSectionProps) {
  const isPending = testState.status === 'pending'
  const isLoadingModels = pickerState.status === 'loading'
  const hasModels = pickerState.status === 'loaded' && pickerState.models.length > 0
  const meta = KNOWN_PROVIDERS[provider]
  const isCustomBaseUrl = !meta?.baseUrl || provider === 'openai-compatible' || provider === 'custom'

  return (
    <div className="panel stack provider-panel">
      <div className="provider-header">
        <h2>{title}</h2>
        <span className={configured ? 'secret-state configured' : 'secret-state'}>
          {configured ? 'Key saved' : 'No key'}
        </span>
      </div>

      <label>
        Provider
        <select value={provider} onChange={(e) => onProvider(e.target.value)}>
          <optgroup label="Popular platforms">
            <option value="siliconflow">硅基流动 (SiliconFlow)</option>
            <option value="aliyun-bailian">阿里云百炼</option>
            <option value="baidu-qianfan">百度千帆</option>
            <option value="volcengine">火山引擎</option>
            <option value="zhipu">智谱 AI (Zhipu)</option>
            <option value="moonshot">月之暗面 (Moonshot)</option>
            <option value="deepseek">DeepSeek</option>
          </optgroup>
          <optgroup label="International">
            <option value="openai">OpenAI</option>
            <option value="openrouter">OpenRouter</option>
            <option value="groq">Groq</option>
            <option value="together">Together AI</option>
            <option value="mistral">Mistral AI</option>
          </optgroup>
          <optgroup label="Self-hosted">
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
            <option value="vllm">vLLM</option>
          </optgroup>
          <optgroup label="Other">
            <option value="openai-compatible">OpenAI Compatible</option>
            <option value="custom">Custom</option>
          </optgroup>
        </select>
      </label>

      {isCustomBaseUrl && (
        <label>Base URL<input value={baseUrl} onChange={(e) => onBaseUrl(e.target.value)} placeholder="https://…/v1" /></label>
      )}
      {!isCustomBaseUrl && (
        <div className="setting-row base-url-display">
          <span className="base-url-label">Base URL</span>
          <span className="base-url-value">{meta.baseUrl}</span>
        </div>
      )}

      <label>
        API key
        <input
          type="password"
          value={apiKey}
          placeholder={configured ? '••••••••  (leave blank to keep saved key)' : 'Enter API key…'}
          onChange={(e) => onApiKey(e.target.value)}
        />
      </label>

      <ModelPickerField
        kind={kind}
        model={model}
        pickerState={pickerState}
        onModel={onModel}
        onLoadModels={onLoadModels}
        isLoadingModels={isLoadingModels}
        hasModels={hasModels}
      />

      {children}

      <div className="test-row">
        <button type="button" className="button test-btn" onClick={onTest} disabled={isPending}>
          {isPending
            ? <><Loader2 size={14} className="spin" /> Testing…</>
            : <><Zap size={14} /> Test connection</>}
        </button>
        <TestResultBadge state={testState} kind={kind} />
      </div>
    </div>
  )
}

// ── ModelPickerField ──────────────────────────────────────────────────────────

interface ModelPickerFieldProps {
  kind: ConnectionTestKind
  model: string
  pickerState: ModelPickerState
  onModel: (v: string) => void
  onLoadModels: () => void
  isLoadingModels: boolean
  hasModels: boolean
}

function groupModelsByOwner(models: ModelInfo[]): Map<string, ModelInfo[]> {
  const groups = new Map<string, ModelInfo[]>()
  for (const m of models) {
    const owner = m.owned_by || 'Other'
    if (!groups.has(owner)) groups.set(owner, [])
    groups.get(owner)!.push(m)
  }
  return groups
}

function ModelPickerField({
  kind, model, pickerState, onModel, onLoadModels, isLoadingModels, hasModels,
}: ModelPickerFieldProps) {
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  // Close dropdown when clicking outside
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  if (!hasModels) {
    return (
      <div className="model-picker-row">
        <label style={{ flex: 1 }}>
          Model
          <input
            value={model}
            onChange={(e) => onModel(e.target.value)}
            placeholder="e.g. gpt-4o-mini"
          />
        </label>
        <button
          type="button"
          className="button load-models-btn"
          onClick={onLoadModels}
          disabled={isLoadingModels}
          title="Fetch available models from provider"
        >
          {isLoadingModels
            ? <Loader2 size={14} className="spin" />
            : <RefreshCw size={14} />}
          {isLoadingModels ? 'Loading…' : 'Load models'}
        </button>
        {pickerState.status === 'error' && (
          <span className="model-load-error" title={pickerState.error ?? undefined}>
            <XCircle size={13} /> Failed
          </span>
        )}
      </div>
    )
  }

  // Models are loaded — show grouped dropdown
  const groups = groupModelsByOwner(pickerState.models)
  const lowerSearch = search.toLowerCase()
  const filteredGroups = new Map<string, ModelInfo[]>()
  for (const [owner, models] of groups) {
    const filtered = models.filter((m) => m.id.toLowerCase().includes(lowerSearch))
    if (filtered.length > 0) filteredGroups.set(owner, filtered)
  }
  const totalFiltered = [...filteredGroups.values()].reduce((n, ms) => n + ms.length, 0)

  return (
    <div className="model-picker-row">
      <label style={{ flex: 1 }}>
        Model
        <div className="model-dropdown-wrapper" ref={dropdownRef}>
          <button
            type="button"
            className="model-dropdown-trigger"
            onClick={() => { setOpen((o) => !o); setSearch('') }}
          >
            <span className="model-dropdown-value">{model || 'Select a model…'}</span>
            <ChevronDown size={14} className={open ? 'chevron open' : 'chevron'} />
          </button>

          {open && (
            <div className="model-dropdown-panel">
              <div className="model-search-row">
                <input
                  autoFocus
                  className="model-search"
                  placeholder="Search models…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <span className="model-count">{totalFiltered}</span>
              </div>
              <div className="model-list">
                {[...filteredGroups.entries()].map(([owner, models]) => (
                  <div key={owner} className="model-group">
                    <div className="model-group-label">{owner}</div>
                    {models.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        className={`model-option ${m.id === model ? 'selected' : ''}`}
                        onClick={() => { onModel(m.id); setOpen(false) }}
                      >
                        <span className="model-id">{m.id}</span>
                        {m.context_length ? (
                          <span className="model-ctx">{formatCtx(m.context_length)}</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ))}
                {totalFiltered === 0 && (
                  <div className="model-empty">No models match "{search}"</div>
                )}
              </div>
            </div>
          )}
        </div>
      </label>
      <button
        type="button"
        className="button load-models-btn"
        onClick={onLoadModels}
        disabled={isLoadingModels}
        title="Refresh model list"
      >
        <RefreshCw size={14} className={isLoadingModels ? 'spin' : ''} />
      </button>
    </div>
  )
}

function formatCtx(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ctx`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k ctx`
  return `${n} ctx`
}

// ── TestResultBadge ───────────────────────────────────────────────────────────

function TestResultBadge({ state, kind }: { state: TestState; kind: ConnectionTestKind }) {
  if (state.status === 'idle' || state.status === 'pending') return null
  if (state.status === 'ok') {
    return (
      <span className="test-result test-result--ok">
        <CheckCircle2 size={13} />
        {state.latency != null ? `${state.latency} ms` : 'OK'}
        {kind === 'embedding' && state.detected_dim != null ? ` · dim ${state.detected_dim}` : ''}
      </span>
    )
  }
  return (
    <span className="test-result test-result--error" title={state.error ?? undefined}>
      <XCircle size={13} /> Failed
    </span>
  )
}

// ── payload serializer ────────────────────────────────────────────────────────

function toPayload(form: SettingsForm): StudioSettingsUpdate {
  return {
    ...form,
    llm_base_url: form.llm_base_url || null,
    llm_api_key: form.llm_api_key || null,
    embedding_base_url: form.embedding_base_url || null,
    embedding_api_key: form.embedding_api_key || null,
    vision_base_url: form.vision_base_url || null,
    vision_api_key: form.vision_api_key || null,
  }
}
