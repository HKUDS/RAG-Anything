import type {
  BrowseDirResponse,
  ConnectionTestRequest,
  ConnectionTestResponse,
  ContentListResponse,
  DocumentRecord,
  EnvironmentResponse,
  GraphLabelsResponse,
  InstallDepRequest,
  InstallDepResponse,
  JobRecord,
  KnowledgeGraphResponse,
  ModelListRequest,
  ModelListResponse,
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

export async function getDocumentContentList(documentId: string): Promise<ContentListResponse> {
  return request<ContentListResponse>(`/api/documents/${documentId}/content-list`)
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

export async function submitQuery(
  question: string,
  mode: string,
  useMultimodal: boolean,
  profileId?: string | null,
  topK?: number | null,
) {
  return request<QueryResponse>('/api/query', {
    body: JSON.stringify({
      question, mode, use_multimodal: useMultimodal,
      profile_id: profileId ?? null,
      top_k: topK ?? null,
    }),
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

export async function testConnection(payload: ConnectionTestRequest): Promise<ConnectionTestResponse> {
  return request<ConnectionTestResponse>('/api/settings/test-connection', {
    body: JSON.stringify(payload),
    method: 'POST',
  })
}

export async function listModels(payload: ModelListRequest): Promise<ModelListResponse> {
  return request<ModelListResponse>('/api/settings/list-models', {
    body: JSON.stringify(payload),
    method: 'POST',
  })
}

export async function installDep(payload: InstallDepRequest): Promise<InstallDepResponse> {
  return request<InstallDepResponse>('/api/settings/install-dep', {
    body: JSON.stringify(payload),
    method: 'POST',
  })
}

export async function browseDir(path: string): Promise<BrowseDirResponse> {
  return request<BrowseDirResponse>(`/api/settings/browse-dir?path=${encodeURIComponent(path)}`)
}

export async function getGraphLabels(profileId?: string | null): Promise<GraphLabelsResponse> {
  const params = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ''
  return request<GraphLabelsResponse>(`/api/graph/labels${params}`)
}

export async function getGraphSubgraph(
  nodeLabel?: string | null,
  maxDepth = 3,
  maxNodes = 150,
  profileId?: string | null,
): Promise<KnowledgeGraphResponse> {
  const params = new URLSearchParams({ max_depth: String(maxDepth), max_nodes: String(maxNodes) })
  if (nodeLabel) params.set('node_label', nodeLabel)
  if (profileId) params.set('profile_id', profileId)
  return request<KnowledgeGraphResponse>(`/api/graph/subgraph?${params}`)
}
