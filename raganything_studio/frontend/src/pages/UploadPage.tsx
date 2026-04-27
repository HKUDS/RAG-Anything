import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileText, Settings, UploadCloud } from 'lucide-react'
import { getEnvironment, getStudioSettings, processDocument, uploadDocument } from '../api/client'
import { useReadiness } from '../context/readiness'
import type { ProcessingPreset, ProcessOptions } from '../types/studio'

const defaultOptions: ProcessOptions = {
  profile_id: null,
  processing_preset: 'balanced',
  enable_profiling: true,
  enable_parse_cache: true,
  enable_modal_cache: true,
  preview_mode: false,
  parser: 'mineru',
  parse_method: 'auto',
  enable_vlm_enhancement: false,
  enable_image_processing: true,
  enable_table_processing: true,
  enable_equation_processing: true,
  max_concurrent_files: 1,
  embedding_batch_size: 16,
  llm_max_concurrency: 2,
  vlm_max_concurrency: 1,
  embedding_max_concurrency: 4,
  retry_max_attempts: 3,
  retry_base_delay: 0.75,
  retry_max_delay: 8,
  write_lock_enabled: true,
  lang: 'ch',
  device: 'cpu',
  start_page: null,
  end_page: null,
}

const presetOptions: Record<ProcessingPreset, Partial<ProcessOptions>> = {
  fast: {
    processing_preset: 'fast',
    enable_vlm_enhancement: false,
    enable_image_processing: false,
    enable_table_processing: false,
    enable_equation_processing: false,
    embedding_batch_size: 32,
    llm_max_concurrency: 2,
    vlm_max_concurrency: 1,
    embedding_max_concurrency: 8,
    retry_max_attempts: 2,
    enable_parse_cache: true,
    enable_modal_cache: true,
  },
  balanced: {
    processing_preset: 'balanced',
    embedding_batch_size: 16,
    llm_max_concurrency: 2,
    vlm_max_concurrency: 1,
    embedding_max_concurrency: 4,
    retry_max_attempts: 3,
    enable_parse_cache: true,
    enable_modal_cache: true,
  },
  deep: {
    processing_preset: 'deep',
    enable_vlm_enhancement: true,
    enable_image_processing: true,
    enable_table_processing: true,
    enable_equation_processing: true,
    embedding_batch_size: 8,
    llm_max_concurrency: 1,
    vlm_max_concurrency: 1,
    embedding_max_concurrency: 2,
    retry_max_attempts: 4,
    enable_parse_cache: true,
    enable_modal_cache: true,
  },
  custom: { processing_preset: 'custom' },
}

export default function UploadPage() {
  const navigate = useNavigate()
  const { fullyConfigured, llmReady, embeddingReady, isLoading: readinessLoading } = useReadiness()
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [textPreview, setTextPreview] = useState<string | null>(null)
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [options, setOptions] = useState<ProcessOptions>(defaultOptions)

  const { data: studioSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: getStudioSettings,
  })

  const { data: environment } = useQuery({
    queryKey: ['environment'],
    queryFn: getEnvironment,
  })

  // Available parsers based on installed packages
  const availableParsers = environment ? [
    environment.mineru_available && 'mineru',
    environment.docling_available && 'docling',
    environment.paddleocr_available && 'paddleocr',
  ].filter(Boolean) as string[] : ['mineru', 'docling', 'paddleocr']

  // Available devices based on hardware/software
  const availableDevices = environment ? [
    'cpu',
    ...(environment.cuda_available ? ['cuda', 'cuda:0'] : []),
    ...(environment.mps_available ? ['mps'] : []),
  ] : ['cpu']

  useEffect(() => {
    if (studioSettings) {
      setOptions((current) => ({
        ...current,
        profile_id: current.profile_id ?? studioSettings.active_profile_id,
        parser: studioSettings.default_parser,
        parse_method: studioSettings.default_parse_method,
        enable_vlm_enhancement: studioSettings.default_enable_vlm_enhancement,
        max_concurrent_files: studioSettings.max_concurrent_files,
        processing_preset: studioSettings.default_processing_preset,
        enable_parse_cache: studioSettings.default_enable_parse_cache,
        enable_modal_cache: studioSettings.default_enable_modal_cache,
        preview_mode: studioSettings.default_preview_mode,
        embedding_batch_size: studioSettings.embedding_batch_size,
        llm_max_concurrency: studioSettings.llm_max_concurrency,
        vlm_max_concurrency: studioSettings.vlm_max_concurrency,
        embedding_max_concurrency: studioSettings.embedding_max_concurrency,
        retry_max_attempts: studioSettings.retry_max_attempts,
        retry_base_delay: studioSettings.retry_base_delay,
        retry_max_delay: studioSettings.retry_max_delay,
        write_lock_enabled: studioSettings.write_lock_enabled,
        lang: studioSettings.default_language,
        device: studioSettings.default_device,
      }))
    }
  }, [studioSettings])

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      setTextPreview(null)
      return
    }

    const objectUrl = URL.createObjectURL(file)
    setPreviewUrl(objectUrl)
    setTextPreview(null)

    if (isTextFile(file)) {
      const reader = new FileReader()
      reader.onload = () => setTextPreview(String(reader.result ?? '').slice(0, 12000))
      reader.onerror = () => setTextPreview(null)
      reader.readAsText(file.slice(0, 12000))
    }

    return () => URL.revokeObjectURL(objectUrl)
  }, [file])

  // Auto-correct parser/device when environment loads and stored default is unavailable
  useEffect(() => {
    if (!environment) return
    setOptions((current) => {
      const parser = availableParsers.includes(current.parser)
        ? current.parser
        : (availableParsers[0] ?? current.parser)
      const device = availableDevices.includes(current.device)
        ? current.device
        : 'cpu'
      return { ...current, parser, device }
    })
  }, [environment])

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a file first')
      return uploadDocument(file)
    },
    onSuccess: (response) => setDocumentId(response.document_id),
  })

  const processMutation = useMutation({
    mutationFn: async () => {
      if (!documentId) throw new Error('Upload the document first')
      return processDocument(documentId, options)
    },
    onSuccess: (response) => navigate(`/jobs/${response.job_id}`),
  })

  function updateOption<K extends keyof ProcessOptions>(key: K, value: ProcessOptions[K]) {
    setOptions((current) => ({
      ...current,
      ...(isPerformanceOverride(key) ? { processing_preset: 'custom' as ProcessingPreset } : {}),
      [key]: value,
    }))
  }

  function applyPreset(preset: ProcessingPreset) {
    setOptions((current) => ({ ...current, ...presetOptions[preset] }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (documentId) {
      processMutation.mutate()
    } else {
      uploadMutation.mutate()
    }
  }

  function handleFileChange(nextFile: File | null) {
    setFile(nextFile)
    setDocumentId(null)
    uploadMutation.reset()
    processMutation.reset()
  }

  const missing: string[] = []
  if (!llmReady) missing.push('LLM API key')
  if (!embeddingReady) missing.push('Embedding API key')
  const selectedProfileName = studioSettings?.profiles.find((profile) => (
    profile.id === (options.profile_id ?? studioSettings.active_profile_id)
  ))?.name ?? 'Default RAG Profile'

  return (
    <section className="page upload-page">
      <div className="page-header">
        <div>
          <h1>Upload Document</h1>
          <p>Choose a document, set parser options, and start an async job</p>
        </div>
      </div>

      {!readinessLoading && !fullyConfigured && (
        <div className="gate-banner">
          <AlertTriangle size={20} className="gate-banner__icon" />
          <div className="gate-banner__body">
            <strong>Configuration required before processing</strong>
            <p>Missing: <b>{missing.join(', ')}</b>. Upload will work, but processing will fail without these keys.</p>
          </div>
          <Link className="button primary" to="/settings">
            <Settings size={16} />
            Go to Settings
          </Link>
        </div>
      )}

      <div className="upload-layout">
        <form className="panel stack upload-form-panel" onSubmit={handleSubmit}>
          <label className="file-picker">
            <UploadCloud size={22} />
            <span>{file ? file.name : 'Choose PDF, image, Office, text, or Markdown file'}</span>
            <input type="file" onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)} />
          </label>

          <div className="form-grid">
            <label>
              Processing preset
              <select value={options.processing_preset} onChange={(e) => applyPreset(e.target.value as ProcessingPreset)}>
                <option value="fast">Fast</option>
                <option value="balanced">Balanced</option>
                <option value="deep">Deep</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            <label>
              RAG profile
              <select
                value={options.profile_id ?? studioSettings?.active_profile_id ?? ''}
                onChange={(e) => updateOption('profile_id', e.target.value)}
              >
                {(studioSettings?.profiles ?? []).map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.name}</option>
                ))}
              </select>
            </label>
            <label>
              Parser
              <select value={options.parser} onChange={(e) => updateOption('parser', e.target.value)}
                disabled={availableParsers.length === 0}>
                {availableParsers.length === 0
                  ? <option value="">No parsers installed</option>
                  : availableParsers.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <label>
              Parse method
              <select value={options.parse_method} onChange={(e) => updateOption('parse_method', e.target.value)}>
                <option value="auto">auto</option>
                <option value="ocr">ocr</option>
                <option value="txt">txt</option>
              </select>
            </label>
            <label>
              Language
              <select value={options.lang} onChange={(e) => updateOption('lang', e.target.value)}>
                <option value="ch">ch</option>
                <option value="en">en</option>
              </select>
            </label>
            <label>
              Device
              <select value={options.device} onChange={(e) => updateOption('device', e.target.value)}>
                {availableDevices.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <label>
              Concurrent files
              <input
                min={1}
                max={32}
                type="number"
                value={options.max_concurrent_files ?? 1}
                onChange={(e) => updateOption('max_concurrent_files', Number(e.target.value))}
              />
            </label>
            <label>
              Page start
              <input
                min={0}
                type="number"
                value={options.start_page ?? ''}
                onChange={(e) => updateOption('start_page', e.target.value === '' ? null : Number(e.target.value))}
              />
            </label>
            <label>
              Page end
              <input
                min={0}
                type="number"
                value={options.end_page ?? ''}
                onChange={(e) => updateOption('end_page', e.target.value === '' ? null : Number(e.target.value))}
              />
            </label>
          </div>

          <div className="toggle-row">
            <label>
              <input checked={options.enable_vlm_enhancement} type="checkbox" onChange={(e) => updateOption('enable_vlm_enhancement', e.target.checked)} />
              VLM enhancement
            </label>
            <label>
              <input checked={options.enable_image_processing} disabled={!options.enable_vlm_enhancement} type="checkbox" onChange={(e) => updateOption('enable_image_processing', e.target.checked)} />
              Image
            </label>
            <label>
              <input checked={options.enable_table_processing} disabled={!options.enable_vlm_enhancement} type="checkbox" onChange={(e) => updateOption('enable_table_processing', e.target.checked)} />
              Table
            </label>
            <label>
              <input checked={options.enable_equation_processing} disabled={!options.enable_vlm_enhancement} type="checkbox" onChange={(e) => updateOption('enable_equation_processing', e.target.checked)} />
              Equation
            </label>
            <label>
              <input checked={options.preview_mode} type="checkbox" onChange={(e) => updateOption('preview_mode', e.target.checked)} />
              Preview only
            </label>
          </div>

          <div className="form-grid">
            <label>
              Embedding batch
              <input min={1} max={1024} type="number" value={options.embedding_batch_size ?? 16} onChange={(e) => updateOption('embedding_batch_size', Number(e.target.value))} />
            </label>
            <label>
              LLM concurrency
              <input min={1} max={64} type="number" value={options.llm_max_concurrency ?? 2} onChange={(e) => updateOption('llm_max_concurrency', Number(e.target.value))} />
            </label>
            <label>
              VLM concurrency
              <input min={1} max={64} type="number" value={options.vlm_max_concurrency ?? 1} onChange={(e) => updateOption('vlm_max_concurrency', Number(e.target.value))} />
            </label>
            <label>
              Embedding concurrency
              <input min={1} max={128} type="number" value={options.embedding_max_concurrency ?? 4} onChange={(e) => updateOption('embedding_max_concurrency', Number(e.target.value))} />
            </label>
            <label>
              Retry attempts
              <input min={1} max={10} type="number" value={options.retry_max_attempts ?? 3} onChange={(e) => updateOption('retry_max_attempts', Number(e.target.value))} />
            </label>
            <label>
              Retry base delay
              <input min={0} max={60} step={0.1} type="number" value={options.retry_base_delay ?? 0.75} onChange={(e) => updateOption('retry_base_delay', Number(e.target.value))} />
            </label>
            <label>
              Retry max delay
              <input min={0} max={300} step={0.1} type="number" value={options.retry_max_delay ?? 8} onChange={(e) => updateOption('retry_max_delay', Number(e.target.value))} />
            </label>
          </div>

          <div className="toggle-row">
            <label>
              <input checked={options.enable_parse_cache} type="checkbox" onChange={(e) => updateOption('enable_parse_cache', e.target.checked)} />
              Parse cache
            </label>
            <label>
              <input checked={options.enable_modal_cache} type="checkbox" onChange={(e) => updateOption('enable_modal_cache', e.target.checked)} />
              Modal cache
            </label>
            <label>
              <input checked={options.write_lock_enabled} type="checkbox" onChange={(e) => updateOption('write_lock_enabled', e.target.checked)} />
              Write lock
            </label>
          </div>

          {uploadMutation.error ? <div className="error-panel">{uploadMutation.error.message}</div> : null}
          {processMutation.error ? <div className="error-panel">{processMutation.error.message}</div> : null}
          {documentId ? <div className="success-panel">Upload complete - ready to process</div> : null}

          <button
            className="button primary"
            disabled={!file || uploadMutation.isPending || processMutation.isPending || (!documentId && !fullyConfigured && !readinessLoading)}
          >
            {documentId ? 'Start Processing' : 'Upload'}
          </button>
        </form>

        <FilePreviewPanel
          documentId={documentId}
          file={file}
          options={options}
          previewUrl={previewUrl}
          profileName={selectedProfileName}
          textPreview={textPreview}
        />
      </div>
    </section>
  )
}

function FilePreviewPanel({
  documentId, file, options, previewUrl, profileName, textPreview,
}: {
  documentId: string | null
  file: File | null
  options: ProcessOptions
  previewUrl: string | null
  profileName: string
  textPreview: string | null
}) {
  const kind = file ? fileKind(file) : 'empty'
  return (
    <aside className="panel upload-preview-panel">
      <div className="upload-preview-header">
        <div>
          <h2>File Preview</h2>
          <p>{file ? file.name : 'No file selected'}</p>
        </div>
        {documentId ? <span className="upload-state-pill"><CheckCircle2 size={13} /> uploaded</span> : null}
      </div>

      <div className={`upload-preview-frame upload-preview-frame--${kind}`}>
        {!file ? (
          <div className="upload-preview-empty">
            <UploadCloud size={32} />
            <strong>Waiting for a document</strong>
            <span>PDF, image, text, Markdown, Office, and HTML files</span>
          </div>
        ) : kind === 'image' && previewUrl ? (
          <img alt={file.name} src={previewUrl} />
        ) : kind === 'pdf' && previewUrl ? (
          <iframe src={`${previewUrl}#toolbar=0&navpanes=0`} title={file.name} />
        ) : kind === 'text' ? (
          <pre>{textPreview || 'Loading text preview...'}</pre>
        ) : (
          <div className="upload-preview-empty">
            <FileText size={34} />
            <strong>{fileExtension(file.name).toUpperCase() || 'DOCUMENT'}</strong>
            <span>{file.type || 'application/octet-stream'}</span>
          </div>
        )}
      </div>

      <div className="upload-preview-meta">
        <PreviewMeta label="Type" value={file ? fileKindLabel(file) : '-'} />
        <PreviewMeta label="Size" value={file ? formatFileSize(file.size) : '-'} />
        <PreviewMeta label="Parser" value={options.parser} />
        <PreviewMeta label="Profile" value={profileName} />
      </div>

      <div className="upload-preview-route">
        <span>{options.processing_preset}</span>
        <span>{options.parse_method}</span>
        <span>{options.device}</span>
        {options.preview_mode ? <span>preview</span> : null}
        {options.enable_vlm_enhancement ? <span>VLM</span> : null}
      </div>
    </aside>
  )
}

function PreviewMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="preview-meta-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function fileKind(file: File): 'image' | 'pdf' | 'text' | 'document' {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) return 'pdf'
  if (isTextFile(file)) return 'text'
  return 'document'
}

function fileKindLabel(file: File) {
  const kind = fileKind(file)
  if (kind === 'image') return 'Image'
  if (kind === 'pdf') return 'PDF'
  if (kind === 'text') return 'Text'
  return fileExtension(file.name).toUpperCase() || 'Document'
}

function isTextFile(file: File) {
  const name = file.name.toLowerCase()
  return file.type.startsWith('text/')
    || ['.md', '.markdown', '.txt', '.csv', '.json', '.html', '.htm', '.log'].some((ext) => name.endsWith(ext))
}

function fileExtension(name: string) {
  const match = name.match(/\.([^.]+)$/)
  return match?.[1] ?? ''
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let size = bytes / 1024
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`
}

function isPerformanceOverride(key: keyof ProcessOptions): boolean {
  return [
    'enable_vlm_enhancement',
    'enable_image_processing',
    'enable_table_processing',
    'enable_equation_processing',
    'embedding_batch_size',
    'llm_max_concurrency',
    'vlm_max_concurrency',
    'embedding_max_concurrency',
    'retry_max_attempts',
    'retry_base_delay',
    'retry_max_delay',
    'enable_parse_cache',
    'enable_modal_cache',
    'preview_mode',
    'write_lock_enabled',
  ].includes(key)
}
