import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Settings, UploadCloud } from 'lucide-react'
import { getStudioSettings, processDocument, uploadDocument } from '../api/client'
import { useReadiness } from '../context/readiness'
import type { ProcessOptions } from '../types/studio'

const defaultOptions: ProcessOptions = {
  parser: 'mineru',
  parse_method: 'auto',
  enable_image_processing: true,
  enable_table_processing: true,
  enable_equation_processing: true,
  lang: 'ch',
  device: 'cpu',
}

export default function UploadPage() {
  const navigate = useNavigate()
  const { fullyConfigured, llmReady, embeddingReady, isLoading: readinessLoading } = useReadiness()
  const [file, setFile] = useState<File | null>(null)
  const [documentId, setDocumentId] = useState<string | null>(null)
  const [options, setOptions] = useState<ProcessOptions>(defaultOptions)

  const { data: studioSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: getStudioSettings,
  })

  useEffect(() => {
    if (studioSettings) {
      setOptions((current) => ({
        ...current,
        parser: studioSettings.default_parser,
        parse_method: studioSettings.default_parse_method,
        lang: studioSettings.default_language,
        device: studioSettings.default_device,
      }))
    }
  }, [studioSettings])

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
    setOptions((current) => ({ ...current, [key]: value }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (documentId) {
      processMutation.mutate()
    } else {
      uploadMutation.mutate()
    }
  }

  const missing: string[] = []
  if (!llmReady) missing.push('LLM API key')
  if (!embeddingReady) missing.push('Embedding API key')

  return (
    <section className="page narrow">
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

      <form className="panel stack" onSubmit={handleSubmit}>
        <label className="file-picker">
          <UploadCloud size={22} />
          <span>{file ? file.name : 'Choose PDF, image, Office, text, or Markdown file'}</span>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>

        <div className="form-grid">
          <label>
            Parser
            <select value={options.parser} onChange={(e) => updateOption('parser', e.target.value)}>
              <option value="mineru">mineru</option>
              <option value="docling">docling</option>
              <option value="paddleocr">paddleocr</option>
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
              <option value="cpu">cpu</option>
              <option value="cuda">cuda</option>
              <option value="cuda:0">cuda:0</option>
              <option value="mps">mps</option>
            </select>
          </label>
        </div>

        <div className="toggle-row">
          <label>
            <input checked={options.enable_image_processing} type="checkbox" onChange={(e) => updateOption('enable_image_processing', e.target.checked)} />
            Image
          </label>
          <label>
            <input checked={options.enable_table_processing} type="checkbox" onChange={(e) => updateOption('enable_table_processing', e.target.checked)} />
            Table
          </label>
          <label>
            <input checked={options.enable_equation_processing} type="checkbox" onChange={(e) => updateOption('enable_equation_processing', e.target.checked)} />
            Equation
          </label>
        </div>

        {uploadMutation.error ? <div className="error-panel">{uploadMutation.error.message}</div> : null}
        {processMutation.error ? <div className="error-panel">{processMutation.error.message}</div> : null}
        {documentId ? <div className="success-panel">Upload complete — ready to process</div> : null}

        <button
          className="button primary"
          disabled={!file || uploadMutation.isPending || processMutation.isPending || (!documentId && !fullyConfigured && !readinessLoading)}
        >
          {documentId ? 'Start Processing' : 'Upload'}
        </button>
      </form>
    </section>
  )
}
