import type {
  DocumentRecord,
  EnvironmentResponse,
  JobRecord,
  ProcessOptions,
  QueryResponse,
  StudioSettings,
  StudioSettingsUpdate,
} from '../types/studio'

const apiBase = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const message = payload?.detail?.message ?? payload?.detail ?? response.statusText
    throw new Error(String(message))
  }

  return response.json() as Promise<T>
}

export async function getDocuments(): Promise<DocumentRecord[]> {
  const response = await request<{ items: DocumentRecord[] }>('/api/documents')
  return response.items
}

export async function uploadDocument(file: File) {
  const body = new FormData()
  body.append('file', file)
  return request<{ document_id: string; filename: string; status: string }>('/api/documents/upload', {
    body,
    method: 'POST',
  })
}

export async function processDocument(documentId: string, options: ProcessOptions) {
  return request<{ job_id: string; status: string }>(`/api/documents/${documentId}/process`, {
    body: JSON.stringify(options),
    method: 'POST',
  })
}

export async function getJob(jobId: string): Promise<JobRecord> {
  return request<JobRecord>(`/api/jobs/${jobId}`)
}

export async function submitQuery(question: string, mode: string, useMultimodal: boolean) {
  return request<QueryResponse>('/api/query', {
    body: JSON.stringify({ question, mode, use_multimodal: useMultimodal }),
    method: 'POST',
  })
}

export async function getEnvironment(): Promise<EnvironmentResponse> {
  return request<EnvironmentResponse>('/api/settings/environment')
}

export async function getStudioSettings(): Promise<StudioSettings> {
  return request<StudioSettings>('/api/settings')
}

export async function updateStudioSettings(settings: StudioSettingsUpdate): Promise<StudioSettings> {
  const response = await request<{ settings: StudioSettings }>('/api/settings', {
    body: JSON.stringify(settings),
    method: 'PUT',
  })
  return response.settings
}
