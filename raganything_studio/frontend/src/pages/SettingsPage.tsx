import { FormEvent, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, KeyRound, Loader2, RotateCcw, Save, ScanSearch, ServerCog, XCircle, Zap } from 'lucide-react'
import { getEnvironment, getStudioSettings, testConnection, updateStudioSettings } from '../api/client'
import type { ConnectionTestKind, ConnectionTestResponse, StudioSettings, StudioSettingsUpdate } from '../types/studio'

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

interface TestState {
  status: 'idle' | 'pending' | 'ok' | 'error'
  latency?: number | null
  error?: string | null
  detected_dim?: number | null
}

const idleTest: TestState = { status: 'idle' }

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [activePanel, setActivePanel] = useState<'models' | 'runtime' | 'defaults'>('models')
  const [form, setForm] = useState<SettingsForm | null>(null)
  const [tests, setTests] = useState<Record<ConnectionTestKind, TestState>>({
    llm: idleTest, embedding: idleTest, vision: idleTest,
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
                configured={settings.llm_api_key_configured} testState={tests.llm}
                onProvider={(v) => updateField('llm_provider', v)}
                onModel={(v) => updateField('llm_model', v)}
                onBaseUrl={(v) => updateField('llm_base_url', v)}
                onApiKey={(v) => updateField('llm_api_key', v)}
                onTest={() => handleTest('llm')}
              />
              <ProviderSection
                title="Embedding" kind="embedding"
                provider={form.embedding_provider} model={form.embedding_model}
                baseUrl={form.embedding_base_url ?? ''} apiKey={form.embedding_api_key}
                configured={settings.embedding_api_key_configured} testState={tests.embedding}
                onProvider={(v) => updateField('embedding_provider', v)}
                onModel={(v) => updateField('embedding_model', v)}
                onBaseUrl={(v) => updateField('embedding_base_url', v)}
                onApiKey={(v) => updateField('embedding_api_key', v)}
                onTest={() => handleTest('embedding')}
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
                configured={settings.vision_api_key_configured} testState={tests.vision}
                onProvider={(v) => updateField('vision_provider', v)}
                onModel={(v) => updateField('vision_model', v)}
                onBaseUrl={(v) => updateField('vision_base_url', v)}
                onApiKey={(v) => updateField('vision_api_key', v)}
                onTest={() => handleTest('vision')}
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

interface ProviderSectionProps {
  title: string
  kind: ConnectionTestKind
  provider: string
  model: string
  baseUrl: string
  apiKey: string
  configured: boolean
  testState: TestState
  onProvider: (v: string) => void
  onModel: (v: string) => void
  onBaseUrl: (v: string) => void
  onApiKey: (v: string) => void
  onTest: () => void
  children?: ReactNode
}

function ProviderSection({
  title, kind, provider, model, baseUrl, apiKey, configured,
  testState, onProvider, onModel, onBaseUrl, onApiKey, onTest, children,
}: ProviderSectionProps) {
  const isPending = testState.status === 'pending'
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
          <option value="openai-compatible">OpenAI compatible</option>
          <option value="openai">OpenAI</option>
          <option value="ollama">Ollama</option>
          <option value="lmstudio">LM Studio</option>
          <option value="vllm">vLLM</option>
          <option value="custom">Custom</option>
        </select>
      </label>
      <label>Model<input value={model} onChange={(e) => onModel(e.target.value)} /></label>
      <label>Base URL<input value={baseUrl} onChange={(e) => onBaseUrl(e.target.value)} /></label>
      <label>
        API key
        <input
          type="password"
          value={apiKey}
          placeholder={configured ? '••••••••  (leave blank to keep saved key)' : ''}
          onChange={(e) => onApiKey(e.target.value)}
        />
      </label>
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
