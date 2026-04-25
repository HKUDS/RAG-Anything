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
  latest_job_id?: string | null
  latest_job_status?: string | null
  latest_job_stage?: string | null
  latest_job_progress?: number | null
  latest_job_message?: string | null
  status_detail?: string | null
  result_available: boolean
  content_items_count?: number | null
  chunks_count?: number | null
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
  stage_durations: Record<string, number>
  api_call_counts: Record<string, number>
  cache_hits: Record<string, number>
  cache_misses: Record<string, number>
  created_at: string
  updated_at: string
}

export type ProcessingPreset = 'fast' | 'balanced' | 'deep' | 'custom'

export interface ProcessOptions {
  profile_id?: string | null
  processing_preset: ProcessingPreset
  enable_profiling: boolean
  enable_parse_cache: boolean
  enable_modal_cache: boolean
  preview_mode: boolean
  parser: string
  parse_method: string
  enable_vlm_enhancement: boolean
  enable_image_processing: boolean
  enable_table_processing: boolean
  enable_equation_processing: boolean
  max_concurrent_files?: number | null
  embedding_batch_size?: number | null
  llm_max_concurrency?: number | null
  vlm_max_concurrency?: number | null
  embedding_max_concurrency?: number | null
  retry_max_attempts?: number | null
  retry_base_delay?: number | null
  retry_max_delay?: number | null
  write_lock_enabled: boolean
  lang: string
  device: string
  start_page?: number | null
  end_page?: number | null
}

export interface QueryResponse {
  answer: string
  sources: Array<Record<string, unknown>>
  raw?: Record<string, unknown> | null
  trace?: Record<string, unknown> | null
}

export interface ContentListResponse {
  document_id: string
  items: Array<Record<string, unknown>>
}

export interface EnvironmentResponse {
  python: string
  raganything_installed: boolean
  lightrag_installed: boolean
  mineru_available: boolean
  docling_available: boolean
  paddleocr_available: boolean
  libreoffice_available: boolean
  cuda_gpu_present: boolean
  cuda_available: boolean
  mps_available: boolean
}

export interface BrowseDirEntry {
  name: string
  path: string
  is_dir: boolean
}

export interface BrowseDirResponse {
  path: string
  parent: string | null
  entries: BrowseDirEntry[]
}

export interface InstallDepRequest {
  package: string
}

export interface InstallDepResponse {
  ok: boolean
  output: string
  error?: string | null
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
  default_enable_vlm_enhancement: boolean
  max_concurrent_files: number
  default_processing_preset: ProcessingPreset
  default_enable_parse_cache: boolean
  default_enable_modal_cache: boolean
  default_preview_mode: boolean
  embedding_batch_size: number
  llm_max_concurrency: number
  vlm_max_concurrency: number
  embedding_max_concurrency: number
  retry_max_attempts: number
  retry_base_delay: number
  retry_max_delay: number
  write_lock_enabled: boolean
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
  kind?: ConnectionTestKind | null
}

export interface ModelListResponse {
  ok: boolean
  models: ModelInfo[]
  error?: string | null
}

export interface GraphNode {
  id: string
  labels: string[]
  properties: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  type: string | null
  source: string
  target: string
  properties: Record<string, unknown>
}

export interface KnowledgeGraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  is_truncated: boolean
}

export interface GraphLabelsResponse {
  labels: string[]
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
  default_enable_vlm_enhancement: boolean
  max_concurrent_files: number
  default_processing_preset: ProcessingPreset
  default_enable_parse_cache: boolean
  default_enable_modal_cache: boolean
  default_preview_mode: boolean
  embedding_batch_size: number
  llm_max_concurrency: number
  vlm_max_concurrency: number
  embedding_max_concurrency: number
  retry_max_attempts: number
  retry_base_delay: number
  retry_max_delay: number
  write_lock_enabled: boolean
  active_profile_id?: string | null
  profiles?: ModelProfileUpdate[] | null
}
