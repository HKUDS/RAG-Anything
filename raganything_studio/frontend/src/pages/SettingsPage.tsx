import { FormEvent, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, KeyRound, RotateCcw, Save, ServerCog } from 'lucide-react'
import { getEnvironment, getStudioSettings, updateStudioSettings } from '../api/client'
import type { StudioSettings, StudioSettingsUpdate } from '../types/studio'

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

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [activePanel, setActivePanel] = useState<'models' | 'runtime' | 'defaults'>('models')
  const [form, setForm] = useState<SettingsForm | null>(null)
  const { data: environment } = useQuery({
    queryKey: ['environment'],
    queryFn: getEnvironment,
  })
  const { data: settings, error } = useQuery({
    queryKey: ['settings'],
    queryFn: getStudioSettings,
  })

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
    },
  })

  const rows = environment
    ? [
        ['Python', environment.python],
        ['RAG-Anything', environment.raganything_installed ? 'available' : 'missing'],
        ['LightRAG', environment.lightrag_installed ? 'available' : 'missing'],
        ['MinerU', environment.mineru_available ? 'available' : 'missing'],
        ['LibreOffice', environment.libreoffice_available ? 'available' : 'missing'],
        ['CUDA', environment.cuda_available ? 'available' : 'missing'],
      ]
    : []

  function updateField<K extends keyof SettingsForm>(key: K, value: SettingsForm[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveMutation.mutate()
  }

  if (error) {
    return <section className="page"><div className="error-panel">{(error as Error).message}</div></section>
  }

  if (!form || !settings) {
    return <section className="page"><div className="empty">Loading settings</div></section>
  }

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Local model providers, credentials, directories, and processing defaults</p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={() => setForm(makeForm(settings))}>
            <RotateCcw size={18} />
            Reset
          </button>
          <button className="button primary" form="studio-settings-form" disabled={saveMutation.isPending}>
            <Save size={18} />
            Save Settings
          </button>
        </div>
      </div>

      <div className="settings-layout">
        <aside className="settings-nav">
          <button className={activePanel === 'models' ? 'active' : ''} onClick={() => setActivePanel('models')}>
            <KeyRound size={18} />
            Models
          </button>
          <button className={activePanel === 'runtime' ? 'active' : ''} onClick={() => setActivePanel('runtime')}>
            <ServerCog size={18} />
            Runtime
          </button>
          <button className={activePanel === 'defaults' ? 'active' : ''} onClick={() => setActivePanel('defaults')}>
            <CheckCircle2 size={18} />
            Defaults
          </button>
        </aside>

        <form className="settings-content" id="studio-settings-form" onSubmit={handleSubmit}>
          {activePanel === 'models' ? (
            <div className="provider-grid">
              <ProviderSection
                title="LLM"
                provider={form.llm_provider}
                model={form.llm_model}
                baseUrl={form.llm_base_url ?? ''}
                apiKey={form.llm_api_key}
                configured={settings.llm_api_key_configured}
                onProvider={(value) => updateField('llm_provider', value)}
                onModel={(value) => updateField('llm_model', value)}
                onBaseUrl={(value) => updateField('llm_base_url', value)}
                onApiKey={(value) => updateField('llm_api_key', value)}
              />
              <ProviderSection
                title="Embedding"
                provider={form.embedding_provider}
                model={form.embedding_model}
                baseUrl={form.embedding_base_url ?? ''}
                apiKey={form.embedding_api_key}
                configured={settings.embedding_api_key_configured}
                onProvider={(value) => updateField('embedding_provider', value)}
                onModel={(value) => updateField('embedding_model', value)}
                onBaseUrl={(value) => updateField('embedding_base_url', value)}
                onApiKey={(value) => updateField('embedding_api_key', value)}
              >
                <label>
                  Dimension
                  <input
                    min={1}
                    type="number"
                    value={form.embedding_dim}
                    onChange={(event) => updateField('embedding_dim', Number(event.target.value))}
                  />
                </label>
                <label>
                  Max tokens
                  <input
                    min={1}
                    type="number"
                    value={form.embedding_max_token_size}
                    onChange={(event) => updateField('embedding_max_token_size', Number(event.target.value))}
                  />
                </label>
              </ProviderSection>
              <ProviderSection
                title="Vision"
                provider={form.vision_provider}
                model={form.vision_model}
                baseUrl={form.vision_base_url ?? ''}
                apiKey={form.vision_api_key}
                configured={settings.vision_api_key_configured}
                onProvider={(value) => updateField('vision_provider', value)}
                onModel={(value) => updateField('vision_model', value)}
                onBaseUrl={(value) => updateField('vision_base_url', value)}
                onApiKey={(value) => updateField('vision_api_key', value)}
              />
            </div>
          ) : null}

          {activePanel === 'runtime' ? (
            <div className="split">
              <div className="panel stack">
                <h2>Directories</h2>
                <label>Data directory<input value={form.data_dir ?? ''} onChange={(event) => updateField('data_dir', event.target.value)} /></label>
                <label>Upload directory<input value={form.upload_dir ?? ''} onChange={(event) => updateField('upload_dir', event.target.value)} /></label>
                <label>Working directory<input value={form.working_dir ?? ''} onChange={(event) => updateField('working_dir', event.target.value)} /></label>
                <label>Output directory<input value={form.output_dir ?? ''} onChange={(event) => updateField('output_dir', event.target.value)} /></label>
                <label>Settings file<input value={settings.settings_file} readOnly /></label>
              </div>
              <div className="panel stack">
                <h2>Environment Check</h2>
                {rows.map(([label, value]) => (
                  <div className="setting-row" key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {activePanel === 'defaults' ? (
            <div className="panel stack compact-settings">
              <h2>Processing Defaults</h2>
              <div className="form-grid">
                <label>
                  Parser
                  <select value={form.default_parser} onChange={(event) => updateField('default_parser', event.target.value)}>
                    <option value="mineru">mineru</option>
                    <option value="docling">docling</option>
                    <option value="paddleocr">paddleocr</option>
                  </select>
                </label>
                <label>
                  Parse method
                  <select value={form.default_parse_method} onChange={(event) => updateField('default_parse_method', event.target.value)}>
                    <option value="auto">auto</option>
                    <option value="ocr">ocr</option>
                    <option value="txt">txt</option>
                  </select>
                </label>
                <label>
                  Language
                  <select value={form.default_language} onChange={(event) => updateField('default_language', event.target.value)}>
                    <option value="ch">ch</option>
                    <option value="en">en</option>
                  </select>
                </label>
                <label>
                  Device
                  <select value={form.default_device} onChange={(event) => updateField('default_device', event.target.value)}>
                    <option value="cpu">cpu</option>
                    <option value="cuda">cuda</option>
                    <option value="cuda:0">cuda:0</option>
                    <option value="mps">mps</option>
                  </select>
                </label>
              </div>
            </div>
          ) : null}

          {saveMutation.error ? <div className="error-panel">{saveMutation.error.message}</div> : null}
          {saveMutation.isSuccess ? <div className="success-panel">Settings saved</div> : null}
        </form>
      </div>
    </section>
  )
}

function ProviderSection({
  title,
  provider,
  model,
  baseUrl,
  apiKey,
  configured,
  onProvider,
  onModel,
  onBaseUrl,
  onApiKey,
  children,
}: {
  title: string
  provider: string
  model: string
  baseUrl: string
  apiKey: string
  configured: boolean
  onProvider: (value: string) => void
  onModel: (value: string) => void
  onBaseUrl: (value: string) => void
  onApiKey: (value: string) => void
  children?: ReactNode
}) {
  return (
    <div className="panel stack provider-panel">
      <div className="provider-header">
        <h2>{title}</h2>
        <span className={configured ? 'secret-state configured' : 'secret-state'}>{configured ? 'Key saved' : 'No key'}</span>
      </div>
      <label>
        Provider
        <select value={provider} onChange={(event) => onProvider(event.target.value)}>
          <option value="openai-compatible">OpenAI compatible</option>
          <option value="openai">OpenAI</option>
          <option value="ollama">Ollama</option>
          <option value="lmstudio">LM Studio</option>
          <option value="vllm">vLLM</option>
          <option value="custom">Custom</option>
        </select>
      </label>
      <label>Model<input value={model} onChange={(event) => onModel(event.target.value)} /></label>
      <label>Base URL<input value={baseUrl} onChange={(event) => onBaseUrl(event.target.value)} /></label>
      <label>API key<input type="password" value={apiKey} onChange={(event) => onApiKey(event.target.value)} /></label>
      {children}
    </div>
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
