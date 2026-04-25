import { FormEvent, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2, ChevronDown, Copy, KeyRound, Loader2, Plus, RefreshCw,
  RotateCcw, Save, ScanSearch, ServerCog, Trash2, XCircle, Zap,
} from 'lucide-react'
import { getEnvironment, getStudioSettings, listModels, testConnection, updateStudioSettings } from '../api/client'
import type {
  ConnectionTestKind, ConnectionTestResponse, ModelInfo, ModelProfile,
  ModelProfileUpdate, StudioSettings, StudioSettingsUpdate,
} from '../types/studio'

interface ProviderMeta {
  label: string
  baseUrl: string
  supportsModelList: boolean
}

const KNOWN_PROVIDERS: Record<string, ProviderMeta> = {
  openai: { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', supportsModelList: true },
  siliconflow: { label: '硅基流动 (SiliconFlow)', baseUrl: 'https://api.siliconflow.cn/v1', supportsModelList: true },
  'aliyun-bailian': { label: '阿里云百炼', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', supportsModelList: true },
  'baidu-qianfan': { label: '百度千帆', baseUrl: 'https://qianfan.baidubce.com/v2', supportsModelList: true },
  volcengine: { label: '火山引擎', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', supportsModelList: true },
  openrouter: { label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', supportsModelList: true },
  deepseek: { label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', supportsModelList: true },
  zhipu: { label: '智谱 AI (Zhipu)', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', supportsModelList: true },
  moonshot: { label: '月之暗面 (Moonshot)', baseUrl: 'https://api.moonshot.cn/v1', supportsModelList: true },
  groq: { label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1', supportsModelList: true },
  together: { label: 'Together AI', baseUrl: 'https://api.together.xyz/v1', supportsModelList: true },
  mistral: { label: 'Mistral AI', baseUrl: 'https://api.mistral.ai/v1', supportsModelList: true },
  ollama: { label: 'Ollama', baseUrl: 'http://localhost:11434/v1', supportsModelList: true },
  lmstudio: { label: 'LM Studio', baseUrl: 'http://localhost:1234/v1', supportsModelList: true },
  vllm: { label: 'vLLM', baseUrl: 'http://localhost:8000/v1', supportsModelList: true },
  'openai-compatible': { label: 'OpenAI Compatible', baseUrl: '', supportsModelList: true },
  custom: { label: 'Custom', baseUrl: '', supportsModelList: false },
}

interface ChannelForm {
  provider: string
  model: string
  base_url: string
  api_key: string
  api_key_configured: boolean
  embedding_dim?: number
  embedding_max_token_size?: number
}

interface ProfileForm {
  id: string
  name: string
  llm: ChannelForm
  embedding: ChannelForm
  vision: ChannelForm
}

interface SettingsForm {
  data_dir: string
  upload_dir: string
  working_dir: string
  output_dir: string
  default_parser: string
  default_parse_method: string
  default_language: string
  default_device: string
  active_profile_id: string
  profiles: ProfileForm[]
}

interface TestState {
  status: 'idle' | 'pending' | 'ok' | 'error'
  latency?: number | null
  error?: string | null
  detected_dim?: number | null
}

interface ModelPickerState {
  status: 'idle' | 'loading' | 'loaded' | 'error'
  models: ModelInfo[]
  error?: string | null
}

const idleTest: TestState = { status: 'idle' }
const idlePicker: ModelPickerState = { status: 'idle', models: [] }

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [activePanel, setActivePanel] = useState<'models' | 'runtime' | 'defaults'>('models')
  const [selectedProfileId, setSelectedProfileId] = useState('default')
  const [selectedKind, setSelectedKind] = useState<ConnectionTestKind>('llm')
  const [form, setForm] = useState<SettingsForm | null>(null)
  const [tests, setTests] = useState<Record<string, TestState>>({})
  const [pickers, setPickers] = useState<Record<string, ModelPickerState>>({})

  const { data: environment } = useQuery({ queryKey: ['environment'], queryFn: getEnvironment })
  const { data: settings, error } = useQuery({ queryKey: ['settings'], queryFn: getStudioSettings })

  useEffect(() => {
    if (!settings) return
    const nextForm = makeForm(settings)
    setForm(nextForm)
    setSelectedProfileId(settings.active_profile_id || nextForm.profiles[0]?.id || 'default')
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!form) throw new Error('Settings are not loaded')
      return updateStudioSettings(toPayload(form))
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated)
      setForm(makeForm(updated))
      setSelectedProfileId(updated.active_profile_id)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  function updateField<K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current))
  }

  function updateProfile(profileId: string, update: Partial<ProfileForm>) {
    setForm((current) => current ? {
      ...current,
      profiles: current.profiles.map((profile) => (
        profile.id === profileId ? { ...profile, ...update } : profile
      )),
    } : current)
  }

  function updateChannel(profileId: string, kind: ConnectionTestKind, update: Partial<ChannelForm>) {
    setForm((current) => current ? {
      ...current,
      profiles: current.profiles.map((profile) => (
        profile.id === profileId
          ? { ...profile, [kind]: { ...profile[kind], ...update } }
          : profile
      )),
    } : current)
  }

  function addProfile() {
    setForm((current) => {
      if (!current) return current
      const base = current.profiles.find((profile) => profile.id === selectedProfileId) ?? current.profiles[0]
      const id = `profile-${Date.now()}`
      const profile = cloneProfile(base, id, 'New RAG Profile')
      setSelectedProfileId(id)
      setSelectedKind('llm')
      return { ...current, profiles: [...current.profiles, profile] }
    })
  }

  function duplicateProfile() {
    if (!form) return
    const base = selectedProfile ?? form.profiles[0]
    if (!base) return
    const id = `profile-${Date.now()}`
    setSelectedProfileId(id)
    setForm({
      ...form,
      profiles: [...form.profiles, cloneProfile(base, id, `${base.name} Copy`)],
    })
  }

  function removeProfile(profileId: string) {
    setForm((current) => {
      if (!current || current.profiles.length <= 1) return current
      const profiles = current.profiles.filter((profile) => profile.id !== profileId)
      const activeProfileId = current.active_profile_id === profileId
        ? profiles[0].id
        : current.active_profile_id
      const selectedId = selectedProfileId === profileId ? profiles[0].id : selectedProfileId
      setSelectedProfileId(selectedId)
      return { ...current, active_profile_id: activeProfileId, profiles }
    })
  }

  function handleProviderChange(profileId: string, kind: ConnectionTestKind, provider: string) {
    const meta = KNOWN_PROVIDERS[provider]
    updateChannel(profileId, kind, {
      provider,
      ...(meta?.baseUrl ? { base_url: meta.baseUrl } : {}),
    })
    setPickers((prev) => ({ ...prev, [stateKey(profileId, kind)]: idlePicker }))
  }

  async function handleLoadModels(profile: ProfileForm, kind: ConnectionTestKind) {
    const key = stateKey(profile.id, kind)
    const channel = profile[kind]
    setPickers((prev) => ({ ...prev, [key]: { status: 'loading', models: [] } }))
    try {
      const result = await listModels({
        provider: channel.provider,
        base_url: channel.base_url || null,
        api_key: channel.api_key || null,
      })
      setPickers((prev) => ({
        ...prev,
        [key]: result.ok
          ? { status: 'loaded', models: result.models }
          : { status: 'error', models: [], error: result.error ?? 'Failed to load models' },
      }))
    } catch (err) {
      setPickers((prev) => ({
        ...prev,
        [key]: {
          status: 'error', models: [],
          error: err instanceof Error ? err.message : String(err),
        },
      }))
    }
  }

  async function handleTest(profile: ProfileForm, kind: ConnectionTestKind) {
    const key = stateKey(profile.id, kind)
    const channel = profile[kind]
    setTests((prev) => ({ ...prev, [key]: { status: 'pending' } }))
    try {
      const result: ConnectionTestResponse = await testConnection({
        kind,
        profile_id: profile.id,
        provider: channel.provider,
        model: channel.model,
        base_url: channel.base_url || null,
        api_key: channel.api_key || null,
        ...(kind === 'embedding'
          ? {
              embedding_dim: channel.embedding_dim,
              embedding_max_token_size: channel.embedding_max_token_size,
            }
          : {}),
      })
      if (result.ok) {
        setTests((prev) => ({
          ...prev,
          [key]: { status: 'ok', latency: result.latency_ms, detected_dim: result.detected_dim },
        }))
        if (kind === 'embedding' && result.detected_dim != null) {
          updateChannel(profile.id, 'embedding', { embedding_dim: result.detected_dim })
        }
      } else {
        setTests((prev) => ({
          ...prev,
          [key]: { status: 'error', error: result.error ?? 'Connection failed' },
        }))
      }
    } catch (err) {
      setTests((prev) => ({
        ...prev,
        [key]: { status: 'error', error: err instanceof Error ? err.message : String(err) },
      }))
    }
  }

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

  const selectedProfile = form.profiles.find((profile) => profile.id === selectedProfileId)
    ?? form.profiles[0]
  const selectedChannel = selectedProfile?.[selectedKind]
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

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Model profiles, credentials, directories, and processing defaults</p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={() => setForm(makeForm(settings))}>
            <RotateCcw size={16} /> Reset
          </button>
          <button className="button primary" form="studio-settings-form" disabled={saveMutation.isPending}>
            <Save size={16} />
            {saveMutation.isPending ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>

      <div className="settings-layout">
        <aside className="settings-nav">
          <button className={activePanel === 'models' ? 'active' : ''} onClick={() => setActivePanel('models')} type="button">
            <KeyRound size={16} /> Models
          </button>
          <button className={activePanel === 'runtime' ? 'active' : ''} onClick={() => setActivePanel('runtime')} type="button">
            <ServerCog size={16} /> Runtime
          </button>
          <button className={activePanel === 'defaults' ? 'active' : ''} onClick={() => setActivePanel('defaults')} type="button">
            <CheckCircle2 size={16} /> Defaults
          </button>
        </aside>

        <form className="settings-content" id="studio-settings-form" onSubmit={handleSubmit}>
          {activePanel === 'models' && selectedProfile && selectedChannel && (
            <div className="model-settings-shell">
              <aside className="model-service-rail">
                <div className="profile-rail-header">
                  <div className="model-service-search">Search RAG profile...</div>
                  <button className="icon-button" type="button" onClick={addProfile} title="Add profile">
                    <Plus size={16} />
                  </button>
                </div>
                <div className="model-service-list">
                  {form.profiles.map((profile) => (
                    <button
                      className={`model-service-item ${selectedProfileId === profile.id ? 'active' : ''}`}
                      key={profile.id}
                      onClick={() => setSelectedProfileId(profile.id)}
                      type="button"
                    >
                      <span className="provider-avatar">{providerInitial(profile.llm.provider)}</span>
                      <span className="model-service-body">
                        <strong>{profile.name}</strong>
                        <small>{profile.llm.model} / {profile.embedding.model}</small>
                      </span>
                      <span className={profileReady(profile) ? 'on-pill' : 'off-pill'}>
                        {form.active_profile_id === profile.id ? 'RAG' : profileReady(profile) ? 'ON' : 'SET'}
                      </span>
                    </button>
                  ))}
                </div>
                <div className="profile-actions">
                  <button className="button" type="button" onClick={duplicateProfile}>
                    <Copy size={14} /> Duplicate
                  </button>
                  <button
                    className="button danger"
                    disabled={form.profiles.length <= 1}
                    type="button"
                    onClick={() => removeProfile(selectedProfile.id)}
                  >
                    <Trash2 size={14} /> Remove
                  </button>
                </div>
              </aside>

              <div className="model-detail-pane">
                <div className="model-detail-hero">
                  <span className="provider-avatar provider-avatar-large">
                    {providerInitial(selectedChannel.provider)}
                  </span>
                  <div>
                    <input
                      className="profile-name-input"
                      value={selectedProfile.name}
                      onChange={(event) => updateProfile(selectedProfile.id, { name: event.target.value })}
                    />
                    <p>{profileReady(selectedProfile) ? 'Ready for RAG selection' : 'LLM and Embedding keys are required'}</p>
                  </div>
                  <button
                    className={form.active_profile_id === selectedProfile.id ? 'button primary' : 'button'}
                    type="button"
                    onClick={() => updateField('active_profile_id', selectedProfile.id)}
                  >
                    {form.active_profile_id === selectedProfile.id ? 'Default for RAG' : 'Use for RAG'}
                  </button>
                </div>

                <div className="profile-tabs">
                  {(['llm', 'embedding', 'vision'] as ConnectionTestKind[]).map((kind) => (
                    <button
                      className={selectedKind === kind ? 'active' : ''}
                      key={kind}
                      type="button"
                      onClick={() => setSelectedKind(kind)}
                    >
                      {kindLabel(kind)}
                      <span className={selectedProfile[kind].api_key_configured || selectedProfile[kind].api_key ? 'tab-dot ok' : 'tab-dot'} />
                    </button>
                  ))}
                </div>

                <ProviderSection
                  key={`${selectedProfile.id}-${selectedKind}`}
                  title={kindLabel(selectedKind)}
                  kind={selectedKind}
                  channel={selectedChannel}
                  testState={tests[stateKey(selectedProfile.id, selectedKind)] ?? idleTest}
                  pickerState={pickers[stateKey(selectedProfile.id, selectedKind)] ?? idlePicker}
                  onProvider={(provider) => handleProviderChange(selectedProfile.id, selectedKind, provider)}
                  onModel={(model) => updateChannel(selectedProfile.id, selectedKind, { model })}
                  onBaseUrl={(baseUrl) => updateChannel(selectedProfile.id, selectedKind, { base_url: baseUrl })}
                  onApiKey={(apiKey) => updateChannel(selectedProfile.id, selectedKind, { api_key: apiKey })}
                  onTest={() => handleTest(selectedProfile, selectedKind)}
                  onLoadModels={() => handleLoadModels(selectedProfile, selectedKind)}
                >
                  {selectedKind === 'embedding' ? (
                    <>
                      <div className="dim-row">
                        <label style={{ flex: 1 }}>
                          Dimension
                          <input
                            min={1}
                            type="number"
                            value={selectedChannel.embedding_dim ?? 3072}
                            onChange={(event) => updateChannel(
                              selectedProfile.id, 'embedding',
                              { embedding_dim: Number(event.target.value) },
                            )}
                          />
                        </label>
                        {(tests[stateKey(selectedProfile.id, 'embedding')]?.status === 'ok'
                          && tests[stateKey(selectedProfile.id, 'embedding')]?.detected_dim != null) ? (
                            <span className="dim-detected">
                              <ScanSearch size={13} />
                              Auto-detected: {tests[stateKey(selectedProfile.id, 'embedding')]?.detected_dim}
                            </span>
                          ) : null}
                      </div>
                      <label>
                        Max tokens
                        <input
                          min={1}
                          type="number"
                          value={selectedChannel.embedding_max_token_size ?? 8192}
                          onChange={(event) => updateChannel(
                            selectedProfile.id, 'embedding',
                            { embedding_max_token_size: Number(event.target.value) },
                          )}
                        />
                      </label>
                    </>
                  ) : null}
                </ProviderSection>
              </div>
            </div>
          )}

          {activePanel === 'runtime' && (
            <div className="split">
              <div className="panel stack">
                <h2>Directories</h2>
                <label>Data directory<input value={form.data_dir} onChange={(e) => updateField('data_dir', e.target.value)} /></label>
                <label>Upload directory<input value={form.upload_dir} onChange={(e) => updateField('upload_dir', e.target.value)} /></label>
                <label>Working directory<input value={form.working_dir} onChange={(e) => updateField('working_dir', e.target.value)} /></label>
                <label>Output directory<input value={form.output_dir} onChange={(e) => updateField('output_dir', e.target.value)} /></label>
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

interface ProviderSectionProps {
  title: string
  kind: ConnectionTestKind
  channel: ChannelForm
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
  title, kind, channel, testState, pickerState, onProvider, onModel,
  onBaseUrl, onApiKey, onTest, onLoadModels, children,
}: ProviderSectionProps) {
  const isPending = testState.status === 'pending'
  const isLoadingModels = pickerState.status === 'loading'
  const hasModels = pickerState.status === 'loaded' && pickerState.models.length > 0
  const meta = KNOWN_PROVIDERS[channel.provider]
  const isCustomBaseUrl = !meta?.baseUrl || channel.provider === 'openai-compatible' || channel.provider === 'custom'
  const configured = channel.api_key_configured || Boolean(channel.api_key)

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
        <select value={channel.provider} onChange={(e) => onProvider(e.target.value)}>
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

      {isCustomBaseUrl ? (
        <label>Base URL<input value={channel.base_url} onChange={(e) => onBaseUrl(e.target.value)} placeholder="https://.../v1" /></label>
      ) : (
        <div className="setting-row base-url-display">
          <span className="base-url-label">Base URL</span>
          <span className="base-url-value">{meta.baseUrl}</span>
        </div>
      )}

      <label>
        API key
        <input
          type="password"
          value={channel.api_key}
          placeholder={channel.api_key_configured ? 'Saved key, leave blank to keep it' : 'Enter API key...'}
          onChange={(e) => onApiKey(e.target.value)}
        />
      </label>

      <ModelPickerField
        kind={kind}
        model={channel.model}
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
            ? <><Loader2 size={14} className="spin" /> Testing...</>
            : <><Zap size={14} /> Test connection</>}
        </button>
        <TestResultBadge state={testState} kind={kind} />
      </div>
      {testState.status === 'error' && testState.error ? (
        <div className="test-error-message">{summarizeProviderError(testState.error)}</div>
      ) : null}
      {pickerState.status === 'error' && pickerState.error ? (
        <div className="test-error-message">{summarizeProviderError(pickerState.error)}</div>
      ) : null}
    </div>
  )
}

interface ModelPickerFieldProps {
  kind: ConnectionTestKind
  model: string
  pickerState: ModelPickerState
  onModel: (v: string) => void
  onLoadModels: () => void
  isLoadingModels: boolean
  hasModels: boolean
}

function ModelPickerField({
  kind, model, pickerState, onModel, onLoadModels, isLoadingModels, hasModels,
}: ModelPickerFieldProps) {
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [visionOnly, setVisionOnly] = useState(kind === 'vision')

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
          <input value={model} onChange={(e) => onModel(e.target.value)} placeholder="e.g. gpt-4o-mini" />
        </label>
        <button
          type="button"
          className="button load-models-btn"
          onClick={onLoadModels}
          disabled={isLoadingModels}
          title="Fetch available models from provider"
        >
          {isLoadingModels ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
          {isLoadingModels ? 'Loading...' : 'Load models'}
        </button>
        {pickerState.status === 'error' ? (
          <span className="model-load-error" title={pickerState.error ?? undefined}>
            <XCircle size={13} /> Failed
          </span>
        ) : null}
      </div>
    )
  }

  const visionCount = pickerState.models.filter((m) => m.vision_capable).length
  const baseModels = visionOnly ? pickerState.models.filter((m) => m.vision_capable) : pickerState.models
  const groups = groupModelsByOwner(baseModels)
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
            <span className="model-dropdown-value">{model || 'Select a model...'}</span>
            <ChevronDown size={14} className={open ? 'chevron open' : 'chevron'} />
          </button>

          {open ? (
            <div className="model-dropdown-panel">
              <div className="model-search-row">
                <input
                  autoFocus
                  className="model-search"
                  placeholder="Search models..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {kind === 'vision' && visionCount > 0 ? (
                  <button
                    type="button"
                    className={`vision-filter-btn ${visionOnly ? 'active' : ''}`}
                    onClick={() => setVisionOnly((v) => !v)}
                    title={visionOnly ? 'Show all models' : 'Show vision-capable models only'}
                  >
                    VL {visionOnly ? `${visionCount}` : 'only'}
                  </button>
                ) : null}
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
                        <span className="model-badges">
                          {m.vision_capable ? <span className="model-badge model-badge--vision">VL</span> : null}
                          {m.context_length ? <span className="model-ctx">{formatCtx(m.context_length)}</span> : null}
                        </span>
                      </button>
                    ))}
                  </div>
                ))}
                {totalFiltered === 0 ? (
                  <div className="model-empty">
                    {visionOnly
                      ? 'No vision-capable models found. Toggle "VL only" to see all.'
                      : `No models match "${search}"`}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
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

function makeForm(settings: StudioSettings): SettingsForm {
  const profiles = settings.profiles.length > 0
    ? settings.profiles.map(profileFromResponse)
    : [legacyProfile(settings)]
  return {
    data_dir: settings.data_dir,
    upload_dir: settings.upload_dir,
    working_dir: settings.working_dir,
    output_dir: settings.output_dir,
    default_parser: settings.default_parser,
    default_parse_method: settings.default_parse_method,
    default_language: settings.default_language,
    default_device: settings.default_device,
    active_profile_id: settings.active_profile_id || profiles[0].id,
    profiles,
  }
}

function profileFromResponse(profile: ModelProfile): ProfileForm {
  return {
    id: profile.id,
    name: profile.name,
    llm: {
      provider: profile.llm.provider,
      model: profile.llm.model,
      base_url: profile.llm.base_url ?? '',
      api_key: '',
      api_key_configured: profile.llm.api_key_configured,
    },
    embedding: {
      provider: profile.embedding.provider,
      model: profile.embedding.model,
      base_url: profile.embedding.base_url ?? '',
      api_key: '',
      api_key_configured: profile.embedding.api_key_configured,
      embedding_dim: profile.embedding.embedding_dim ?? 3072,
      embedding_max_token_size: profile.embedding.embedding_max_token_size ?? 8192,
    },
    vision: {
      provider: profile.vision.provider,
      model: profile.vision.model,
      base_url: profile.vision.base_url ?? '',
      api_key: '',
      api_key_configured: profile.vision.api_key_configured,
    },
  }
}

function legacyProfile(settings: StudioSettings): ProfileForm {
  return {
    id: 'default',
    name: 'Default RAG Profile',
    llm: {
      provider: settings.llm_provider,
      model: settings.llm_model,
      base_url: settings.llm_base_url ?? '',
      api_key: '',
      api_key_configured: settings.llm_api_key_configured,
    },
    embedding: {
      provider: settings.embedding_provider,
      model: settings.embedding_model,
      base_url: settings.embedding_base_url ?? '',
      api_key: '',
      api_key_configured: settings.embedding_api_key_configured,
      embedding_dim: settings.embedding_dim,
      embedding_max_token_size: settings.embedding_max_token_size,
    },
    vision: {
      provider: settings.vision_provider,
      model: settings.vision_model,
      base_url: settings.vision_base_url ?? '',
      api_key: '',
      api_key_configured: settings.vision_api_key_configured,
    },
  }
}

function toPayload(form: SettingsForm): StudioSettingsUpdate {
  const activeProfile = form.profiles.find((profile) => profile.id === form.active_profile_id) ?? form.profiles[0]
  return {
    data_dir: form.data_dir,
    upload_dir: form.upload_dir,
    working_dir: form.working_dir,
    output_dir: form.output_dir,
    llm_provider: activeProfile.llm.provider,
    llm_model: activeProfile.llm.model,
    llm_base_url: activeProfile.llm.base_url || null,
    llm_api_key: activeProfile.llm.api_key || null,
    embedding_provider: activeProfile.embedding.provider,
    embedding_model: activeProfile.embedding.model,
    embedding_dim: activeProfile.embedding.embedding_dim ?? 3072,
    embedding_max_token_size: activeProfile.embedding.embedding_max_token_size ?? 8192,
    embedding_base_url: activeProfile.embedding.base_url || null,
    embedding_api_key: activeProfile.embedding.api_key || null,
    vision_provider: activeProfile.vision.provider,
    vision_model: activeProfile.vision.model,
    vision_base_url: activeProfile.vision.base_url || null,
    vision_api_key: activeProfile.vision.api_key || null,
    default_parser: form.default_parser,
    default_parse_method: form.default_parse_method,
    default_language: form.default_language,
    default_device: form.default_device,
    active_profile_id: form.active_profile_id,
    profiles: form.profiles.map(profileToPayload),
  }
}

function profileToPayload(profile: ProfileForm): ModelProfileUpdate {
  return {
    id: profile.id,
    name: profile.name || profile.id,
    llm: channelToPayload(profile.llm),
    embedding: channelToPayload(profile.embedding),
    vision: channelToPayload(profile.vision),
  }
}

function channelToPayload(channel: ChannelForm) {
  return {
    provider: channel.provider,
    model: channel.model,
    base_url: channel.base_url || null,
    api_key: channel.api_key || null,
    embedding_dim: channel.embedding_dim ?? null,
    embedding_max_token_size: channel.embedding_max_token_size ?? null,
  }
}

function cloneProfile(profile: ProfileForm, id: string, name: string): ProfileForm {
  return {
    id,
    name,
    llm: { ...profile.llm, api_key: '', api_key_configured: false },
    embedding: { ...profile.embedding, api_key: '', api_key_configured: false },
    vision: { ...profile.vision, api_key: '', api_key_configured: false },
  }
}

function stateKey(profileId: string, kind: ConnectionTestKind) {
  return `${profileId}:${kind}`
}

function profileReady(profile: ProfileForm) {
  return Boolean(
    (profile.llm.api_key_configured || profile.llm.api_key)
    && (profile.embedding.api_key_configured || profile.embedding.api_key),
  )
}

function kindLabel(kind: ConnectionTestKind): string {
  if (kind === 'llm') return 'LLM'
  if (kind === 'embedding') return 'Embedding'
  return 'Vision'
}

function groupModelsByOwner(models: ModelInfo[]): Map<string, ModelInfo[]> {
  const groups = new Map<string, ModelInfo[]>()
  for (const model of models) {
    const owner = model.owned_by || 'Other'
    if (!groups.has(owner)) groups.set(owner, [])
    groups.get(owner)!.push(model)
  }
  return groups
}

function formatCtx(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ctx`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k ctx`
  return `${n} ctx`
}

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

function providerName(provider: string): string {
  return KNOWN_PROVIDERS[provider]?.label ?? provider
}

function providerInitial(provider: string): string {
  const label = providerName(provider).trim()
  if (!label) return 'R'
  if (/[\u4e00-\u9fff]/.test(label[0])) return label[0]
  return label.slice(0, 1).toUpperCase()
}

function summarizeProviderError(error: string): string {
  const invalidKey = error.match(/Incorrect API key provided/i)
  if (invalidKey) return 'Invalid API key: the provider rejected the key currently saved in Studio.'

  const code = error.match(/Error code:\s*(\d+)/i)?.[1]
  const message = error.match(/'message':\s*'([^']+)'/)?.[1]
    ?? error.match(/"message":\s*"([^"]+)"/)?.[1]
  const summary = message ?? error
  return code ? `${code}: ${summary}` : summary.slice(0, 220)
}
