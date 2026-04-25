export type DocumentStatus = 'uploaded' | 'processing' | 'indexed' | 'failed'
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface DocumentRecord {
  id: string
  filename: string
  original_path: string
  working_dir: string
  output_dir: string
  status: DocumentStatus
  created_at: string
  updated_at: string
  error?: string | null
}

export interface JobRecord {
  id: string
  document_id?: string | null
  status: JobStatus
  stage: string
  progress: number
  message: string
  logs: string[]
  error?: string | null
  created_at: string
  updated_at: string
}

export interface ProcessOptions {
  profile_id?: string | null
  parser: string
  parse_method: string
  enable_image_processing: boolean
  enable_table_processing: boolean
  enable_equation_processing: boolean
  lang: string
  device: string
}

export interface QueryResponse {
  answer: string
  sources: Array<Record<string, unknown>>
  raw?: Record<string, unknown> | null
  trace?: Record<string, unknown> | null
}

export interface EnvironmentResponse {
  python: string
  raganything_installed: boolean
  lightrag_installed: boolean
  mineru_available: boolean
  libreoffice_available: boolean
  cuda_available: boolean
}

export interface StudioSettings {
  data_dir: string
  upload_dir: string
  working_dir: string
  output_dir: string
  settings_file: string
  llm_provider: string
  llm_model: string
  llm_base_url?: string | null
  llm_api_key_configured: boolean
  embedding_provider: string
  embedding_model: string
  embedding_dim: number
  embedding_max_token_size: number
  embedding_base_url?: string | null
  embedding_api_key_configured: boolean
  vision_provider: string
  vision_model: string
  vision_base_url?: string | null
  vision_api_key_configured: boolean
  default_parser: string
  default_parse_method: string
  default_language: string
  default_device: string
  active_profile_id: string
  profiles: ModelProfile[]
}

export type ConnectionTestKind = 'llm' | 'embedding' | 'vision'

export interface ModelChannel {
  provider: string
  model: string
  base_url?: string | null
  api_key_configured: boolean
  embedding_dim?: number | null
  embedding_max_token_size?: number | null
}

export interface ModelProfile {
  id: string
  name: string
  llm: ModelChannel
  embedding: ModelChannel
  vision: ModelChannel
}

export interface ModelChannelUpdate {
  provider: string
  model: string
  base_url?: string | null
  api_key?: string | null
  embedding_dim?: number | null
  embedding_max_token_size?: number | null
}

export interface ModelProfileUpdate {
  id: string
  name: string
  llm: ModelChannelUpdate
  embedding: ModelChannelUpdate
  vision: ModelChannelUpdate
}

export interface ConnectionTestRequest {
  kind: ConnectionTestKind
  profile_id?: string | null
  provider: string
  model: string
  base_url?: string | null
  api_key?: string | null
  embedding_dim?: number
  embedding_max_token_size?: number
}

export interface ConnectionTestResponse {
  ok: boolean
  latency_ms?: number | null
  error?: string | null
  detected_dim?: number | null
}

export interface ModelInfo {
  id: string
  owned_by: string
  context_length?: number | null
  vision_capable?: boolean
}

export interface ModelListRequest {
  provider: string
  base_url?: string | null
  api_key?: string | null
}

export interface ModelListResponse {
  ok: boolean
  models: ModelInfo[]
  error?: string | null
}

export interface StudioSettingsUpdate {
  data_dir?: string | null
  upload_dir?: string | null
  working_dir?: string | null
  output_dir?: string | null
  llm_provider: string
  llm_model: string
  llm_base_url?: string | null
  llm_api_key?: string | null
  embedding_provider: string
  embedding_model: string
  embedding_dim: number
  embedding_max_token_size: number
  embedding_base_url?: string | null
  embedding_api_key?: string | null
  vision_provider: string
  vision_model: string
  vision_base_url?: string | null
  vision_api_key?: string | null
  default_parser: string
  default_parse_method: string
  default_language: string
  default_device: string
  active_profile_id?: string | null
  profiles?: ModelProfileUpdate[] | null
}
