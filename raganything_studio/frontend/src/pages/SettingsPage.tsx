import { FormEvent, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle2, ChevronDown, Copy, Download, FolderOpen,
  KeyRound, Loader2, Plus, RefreshCw, RotateCcw, Save, ScanSearch,
  Database, ServerCog, Trash2, XCircle, Zap,
} from 'lucide-react'
import {
  browseDir, getEnvironment, getStudioSettings, installDep, listModels,
  testConnection, testStorageConnection, updateStudioSettings,
} from '../api/client'
import type { BrowseDirEntry } from '../types/studio'
import type {
  ConnectionTestKind, ConnectionTestResponse, ModelInfo, ModelProfile, ProcessingPreset,
  ModelProfileUpdate, StudioSettings, StudioSettingsUpdate,
} from '../types/studio'

interface ProviderMeta {
  label: string
  baseUrl: string
  supportsModelList: boolean
  auth: 'required' | 'optional'
  local?: boolean
}

const KNOWN_PROVIDERS: Record<string, ProviderMeta> = {
  openai: { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', supportsModelList: true, auth: 'required' },
  siliconflow: { label: '硅基流动 (SiliconFlow)', baseUrl: 'https://api.siliconflow.cn/v1', supportsModelList: true, auth: 'required' },
  'aliyun-bailian': { label: '阿里云百炼', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', supportsModelList: true, auth: 'required' },
  'baidu-qianfan': { label: '百度千帆', baseUrl: 'https://qianfan.baidubce.com/v2', supportsModelList: true, auth: 'required' },
  volcengine: { label: '火山引擎', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', supportsModelList: true, auth: 'required' },
  openrouter: { label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', supportsModelList: true, auth: 'required' },
  deepseek: { label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', supportsModelList: true, auth: 'required' },
  zhipu: { label: '智谱 AI (Zhipu)', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', supportsModelList: true, auth: 'required' },
  moonshot: { label: '月之暗面 (Moonshot)', baseUrl: 'https://api.moonshot.cn/v1', supportsModelList: true, auth: 'required' },
  groq: { label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1', supportsModelList: true, auth: 'required' },
  together: { label: 'Together AI', baseUrl: 'https://api.together.xyz/v1', supportsModelList: true, auth: 'required' },
  mistral: { label: 'Mistral AI', baseUrl: 'https://api.mistral.ai/v1', supportsModelList: true, auth: 'required' },
  ollama: { label: 'Ollama', baseUrl: 'http://localhost:11434/v1', supportsModelList: true, auth: 'optional', local: true },
  lmstudio: { label: 'LM Studio', baseUrl: 'http://localhost:1234/v1', supportsModelList: true, auth: 'optional', local: true },
  vllm: { label: 'vLLM', baseUrl: 'http://localhost:8000/v1', supportsModelList: true, auth: 'optional', local: true },
  'openai-compatible': { label: 'OpenAI Compatible', baseUrl: '', supportsModelList: true, auth: 'optional' },
  custom: { label: 'Custom', baseUrl: '', supportsModelList: false, auth: 'optional' },
}

type StoragePresetKey =
  | 'local'
  | 'localFaiss'
  | 'qdrant'
  | 'milvus'
  | 'postgres'
  | 'mongodb'
  | 'opensearch'
  | 'neo4j'
  | 'memgraph'
type StorageLayerKey = 'kv' | 'vector' | 'graph' | 'docStatus'
type StorageLocationKey =
  | 'local'
  | 'faiss'
  | 'qdrant'
  | 'milvus'
  | 'postgres'
  | 'redis'
  | 'mongodb'
  | 'opensearch'
  | 'neo4j'
  | 'memgraph'

interface StorageLayerOption {
  location: StorageLocationKey
  label: string
  className: string
  description: string
  connectionGroup?: StorageConnectionGroupKey
}

interface StoragePreset {
  label: string
  description: string
  kv_storage: string
  vector_storage: string
  graph_storage: string
  doc_status_storage: string
}

type StorageConnectionGroupKey =
  | 'qdrant'
  | 'milvus'
  | 'postgres'
  | 'redis'
  | 'mongodb'
  | 'opensearch'
  | 'neo4j'
  | 'memgraph'

interface StorageConnectionField {
  key: string
  label: string
  type?: 'text' | 'password' | 'number' | 'select'
  placeholder?: string
  options?: Array<{ value: string; label: string }>
}

interface StorageConnectionGroup {
  label: string
  description: string
  fields: StorageConnectionField[]
}

const STORAGE_LAYER_LABELS: Record<StorageLayerKey, string> = {
  kv: 'KV metadata',
  vector: 'Vector index',
  graph: 'Knowledge graph',
  docStatus: 'Document status',
}

const STORAGE_LAYER_OPTIONS: Record<StorageLayerKey, StorageLayerOption[]> = {
  kv: [
    { location: 'local', label: 'Local files', className: 'JsonKVStorage', description: 'JSON metadata in the local workspace.' },
    { location: 'redis', label: 'Redis', className: 'RedisKVStorage', description: 'Remote Redis key-value store.', connectionGroup: 'redis' },
    { location: 'postgres', label: 'Postgres', className: 'PGKVStorage', description: 'Postgres tables for KV metadata.', connectionGroup: 'postgres' },
    { location: 'mongodb', label: 'MongoDB', className: 'MongoKVStorage', description: 'MongoDB collections for KV metadata.', connectionGroup: 'mongodb' },
    { location: 'opensearch', label: 'OpenSearch', className: 'OpenSearchKVStorage', description: 'OpenSearch indexes for KV metadata.', connectionGroup: 'opensearch' },
  ],
  vector: [
    { location: 'local', label: 'NanoVectorDB', className: 'NanoVectorDBStorage', description: 'Local NanoVectorDB files.' },
    { location: 'faiss', label: 'FAISS', className: 'FaissVectorDBStorage', description: 'Local FAISS index files.' },
    { location: 'qdrant', label: 'Qdrant', className: 'QdrantVectorDBStorage', description: 'Remote Qdrant collection.', connectionGroup: 'qdrant' },
    { location: 'milvus', label: 'Milvus / Zilliz', className: 'MilvusVectorDBStorage', description: 'Remote Milvus or Zilliz collection.', connectionGroup: 'milvus' },
    { location: 'postgres', label: 'Postgres pgvector', className: 'PGVectorStorage', description: 'Postgres pgvector tables.', connectionGroup: 'postgres' },
    { location: 'mongodb', label: 'MongoDB Atlas', className: 'MongoVectorDBStorage', description: 'MongoDB vector search collections.', connectionGroup: 'mongodb' },
    { location: 'opensearch', label: 'OpenSearch k-NN', className: 'OpenSearchVectorDBStorage', description: 'OpenSearch vector indexes.', connectionGroup: 'opensearch' },
  ],
  graph: [
    { location: 'local', label: 'Local NetworkX', className: 'NetworkXStorage', description: 'Local NetworkX graph files.' },
    { location: 'neo4j', label: 'Neo4j', className: 'Neo4JStorage', description: 'Neo4j graph database.', connectionGroup: 'neo4j' },
    { location: 'memgraph', label: 'Memgraph', className: 'MemgraphStorage', description: 'Memgraph graph database.', connectionGroup: 'memgraph' },
    { location: 'postgres', label: 'Postgres AGE', className: 'PGGraphStorage', description: 'Postgres with Apache AGE graph tables.', connectionGroup: 'postgres' },
    { location: 'mongodb', label: 'MongoDB', className: 'MongoGraphStorage', description: 'MongoDB graph collections.', connectionGroup: 'mongodb' },
    { location: 'opensearch', label: 'OpenSearch', className: 'OpenSearchGraphStorage', description: 'OpenSearch graph indexes.', connectionGroup: 'opensearch' },
  ],
  docStatus: [
    { location: 'local', label: 'Local JSON', className: 'JsonDocStatusStorage', description: 'Local JSON document status file.' },
    { location: 'redis', label: 'Redis', className: 'RedisDocStatusStorage', description: 'Remote Redis document status.', connectionGroup: 'redis' },
    { location: 'postgres', label: 'Postgres', className: 'PGDocStatusStorage', description: 'Postgres document status table.', connectionGroup: 'postgres' },
    { location: 'mongodb', label: 'MongoDB', className: 'MongoDocStatusStorage', description: 'MongoDB document status collection.', connectionGroup: 'mongodb' },
    { location: 'opensearch', label: 'OpenSearch', className: 'OpenSearchDocStatusStorage', description: 'OpenSearch document status index.', connectionGroup: 'opensearch' },
  ],
}

const STORAGE_CONNECTION_GROUPS: Record<StorageConnectionGroupKey, StorageConnectionGroup> = {
  qdrant: {
    label: 'Qdrant connection',
    description: 'Endpoint used by QdrantVectorDBStorage.',
    fields: [
      { key: 'QDRANT_URL', label: 'URL', placeholder: 'http://localhost:6333' },
      { key: 'QDRANT_API_KEY', label: 'API key', type: 'password' },
    ],
  },
  milvus: {
    label: 'Milvus / Zilliz connection',
    description: 'Connection used by MilvusVectorDBStorage.',
    fields: [
      { key: 'MILVUS_URI', label: 'URI', placeholder: 'http://localhost:19530' },
      { key: 'MILVUS_DB_NAME', label: 'Database', placeholder: 'lightrag' },
      { key: 'MILVUS_USER', label: 'User' },
      { key: 'MILVUS_PASSWORD', label: 'Password', type: 'password' },
      { key: 'MILVUS_TOKEN', label: 'Token', type: 'password' },
    ],
  },
  postgres: {
    label: 'Postgres connection',
    description: 'Shared by PG KV, pgvector, PG graph, and PG document status storage.',
    fields: [
      { key: 'POSTGRES_HOST', label: 'Host', placeholder: 'localhost' },
      { key: 'POSTGRES_PORT', label: 'Port', type: 'number', placeholder: '5432' },
      { key: 'POSTGRES_DATABASE', label: 'Database', placeholder: 'raganything' },
      { key: 'POSTGRES_USER', label: 'User', placeholder: 'postgres' },
      { key: 'POSTGRES_PASSWORD', label: 'Password', type: 'password' },
      { key: 'POSTGRES_MAX_CONNECTIONS', label: 'Max connections', type: 'number', placeholder: '12' },
      {
        key: 'POSTGRES_SSL_MODE',
        label: 'SSL mode',
        type: 'select',
        options: [
          { value: '', label: 'Default' },
          { value: 'disable', label: 'disable' },
          { value: 'allow', label: 'allow' },
          { value: 'prefer', label: 'prefer' },
          { value: 'require', label: 'require' },
          { value: 'verify-ca', label: 'verify-ca' },
          { value: 'verify-full', label: 'verify-full' },
        ],
      },
    ],
  },
  redis: {
    label: 'Redis connection',
    description: 'Connection URI used by Redis KV and document status storage.',
    fields: [
      { key: 'REDIS_URI', label: 'URI', placeholder: 'redis://localhost:6379' },
      { key: 'REDIS_MAX_CONNECTIONS', label: 'Max connections', type: 'number', placeholder: '200' },
    ],
  },
  mongodb: {
    label: 'MongoDB connection',
    description: 'Connection used by MongoDB KV, vector, graph, and document status storage.',
    fields: [
      { key: 'MONGO_URI', label: 'URI', placeholder: 'mongodb://localhost:27017/' },
      { key: 'MONGO_DATABASE', label: 'Database', placeholder: 'LightRAG' },
    ],
  },
  opensearch: {
    label: 'OpenSearch connection',
    description: 'Connection used by OpenSearch KV, vector, graph, and document status storage.',
    fields: [
      { key: 'OPENSEARCH_HOSTS', label: 'Hosts', placeholder: 'localhost:9200' },
      { key: 'OPENSEARCH_USER', label: 'User', placeholder: 'admin' },
      { key: 'OPENSEARCH_PASSWORD', label: 'Password', type: 'password' },
      {
        key: 'OPENSEARCH_USE_SSL',
        label: 'Use SSL',
        type: 'select',
        options: [
          { value: 'true', label: 'true' },
          { value: 'false', label: 'false' },
        ],
      },
      {
        key: 'OPENSEARCH_VERIFY_CERTS',
        label: 'Verify certs',
        type: 'select',
        options: [
          { value: 'false', label: 'false' },
          { value: 'true', label: 'true' },
        ],
      },
    ],
  },
  neo4j: {
    label: 'Neo4j connection',
    description: 'Connection used by Neo4JStorage for the knowledge graph.',
    fields: [
      { key: 'NEO4J_URI', label: 'URI', placeholder: 'neo4j+s://host.databases.neo4j.io' },
      { key: 'NEO4J_USERNAME', label: 'User', placeholder: 'neo4j' },
      { key: 'NEO4J_PASSWORD', label: 'Password', type: 'password' },
      { key: 'NEO4J_DATABASE', label: 'Database', placeholder: 'neo4j' },
    ],
  },
  memgraph: {
    label: 'Memgraph connection',
    description: 'Connection used by MemgraphStorage for the knowledge graph.',
    fields: [
      { key: 'MEMGRAPH_URI', label: 'URI', placeholder: 'bolt://localhost:7687' },
      { key: 'MEMGRAPH_USERNAME', label: 'User' },
      { key: 'MEMGRAPH_PASSWORD', label: 'Password', type: 'password' },
      { key: 'MEMGRAPH_DATABASE', label: 'Database', placeholder: 'memgraph' },
    ],
  },
}

const STORAGE_ENV_DEFAULTS: Record<string, string> = {
  QDRANT_URL: 'http://localhost:6333',
  MILVUS_URI: 'http://localhost:19530',
  MILVUS_DB_NAME: 'lightrag',
  POSTGRES_HOST: 'localhost',
  POSTGRES_PORT: '5432',
  POSTGRES_DATABASE: 'raganything',
  POSTGRES_USER: 'postgres',
  POSTGRES_MAX_CONNECTIONS: '12',
  REDIS_URI: 'redis://localhost:6379',
  MONGO_URI: 'mongodb://localhost:27017/',
  MONGO_DATABASE: 'LightRAG',
  OPENSEARCH_HOSTS: 'localhost:9200',
  OPENSEARCH_USER: 'admin',
  OPENSEARCH_USE_SSL: 'true',
  OPENSEARCH_VERIFY_CERTS: 'false',
  NEO4J_USERNAME: 'neo4j',
  MEMGRAPH_URI: 'bolt://localhost:7687',
  MEMGRAPH_DATABASE: 'memgraph',
}

const STORAGE_PRESETS: Record<StoragePresetKey, StoragePreset> = {
  local: {
    label: 'Local files',
    description: 'JSON, NanoVectorDB, and NetworkX for single-machine experiments.',
    kv_storage: 'JsonKVStorage',
    vector_storage: 'NanoVectorDBStorage',
    graph_storage: 'NetworkXStorage',
    doc_status_storage: 'JsonDocStatusStorage',
  },
  localFaiss: {
    label: 'Local FAISS',
    description: 'Local JSON metadata, FAISS vectors, and NetworkX graph files.',
    kv_storage: 'JsonKVStorage',
    vector_storage: 'FaissVectorDBStorage',
    graph_storage: 'NetworkXStorage',
    doc_status_storage: 'JsonDocStatusStorage',
  },
  qdrant: {
    label: 'Qdrant vector',
    description: 'Remote Qdrant vectors with local JSON KV, graph, and status files.',
    kv_storage: 'JsonKVStorage',
    vector_storage: 'QdrantVectorDBStorage',
    graph_storage: 'NetworkXStorage',
    doc_status_storage: 'JsonDocStatusStorage',
  },
  milvus: {
    label: 'Milvus vector',
    description: 'Milvus or Zilliz vector retrieval with local metadata stores.',
    kv_storage: 'JsonKVStorage',
    vector_storage: 'MilvusVectorDBStorage',
    graph_storage: 'NetworkXStorage',
    doc_status_storage: 'JsonDocStatusStorage',
  },
  postgres: {
    label: 'Postgres stack',
    description: 'PG KV, pgvector, PG graph, and PG document status in one database.',
    kv_storage: 'PGKVStorage',
    vector_storage: 'PGVectorStorage',
    graph_storage: 'PGGraphStorage',
    doc_status_storage: 'PGDocStatusStorage',
  },
  mongodb: {
    label: 'MongoDB stack',
    description: 'MongoDB KV, vector, graph, and document status collections.',
    kv_storage: 'MongoKVStorage',
    vector_storage: 'MongoVectorDBStorage',
    graph_storage: 'MongoGraphStorage',
    doc_status_storage: 'MongoDocStatusStorage',
  },
  opensearch: {
    label: 'OpenSearch stack',
    description: 'OpenSearch KV, k-NN vector, graph, and status indexes.',
    kv_storage: 'OpenSearchKVStorage',
    vector_storage: 'OpenSearchVectorDBStorage',
    graph_storage: 'OpenSearchGraphStorage',
    doc_status_storage: 'OpenSearchDocStatusStorage',
  },
  neo4j: {
    label: 'Neo4j graph',
    description: 'Local files for KV/vector/status with Neo4j for graph storage.',
    kv_storage: 'JsonKVStorage',
    vector_storage: 'NanoVectorDBStorage',
    graph_storage: 'Neo4JStorage',
    doc_status_storage: 'JsonDocStatusStorage',
  },
  memgraph: {
    label: 'Memgraph graph',
    description: 'Local files for KV/vector/status with Memgraph for graph storage.',
    kv_storage: 'JsonKVStorage',
    vector_storage: 'NanoVectorDBStorage',
    graph_storage: 'MemgraphStorage',
    doc_status_storage: 'JsonDocStatusStorage',
  },
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
  kv_storage: string
  vector_storage: string
  graph_storage: string
  doc_status_storage: string
  vector_db_storage_cls_kwargs: Record<string, unknown>
  storage_env: Record<string, string>
  storage_env_configured: Record<string, boolean>
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
  const [activePanel, setActivePanel] = useState<'models' | 'runtime' | 'storage' | 'defaults'>('models')
  const [selectedProfileId, setSelectedProfileId] = useState('default')
  const [selectedKind, setSelectedKind] = useState<ConnectionTestKind>('llm')
  const [form, setForm] = useState<SettingsForm | null>(null)
  const [tests, setTests] = useState<Record<string, TestState>>({})
  const [pickers, setPickers] = useState<Record<string, ModelPickerState>>({})
  const [storageTests, setStorageTests] = useState<Record<string, TestState>>({})

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

  function applyStoragePreset(presetKey: StoragePresetKey) {
    const preset = STORAGE_PRESETS[presetKey]
    setForm((current) => {
      if (!current) return current
      const next = {
        ...current,
        kv_storage: preset.kv_storage,
        vector_storage: preset.vector_storage,
        graph_storage: preset.graph_storage,
        doc_status_storage: preset.doc_status_storage,
      }
      return {
        ...next,
        storage_env: ensureStorageEnvDefaults(next.storage_env, requiredConnectionGroups(next)),
      }
    })
  }

  function updateStorageEnv(key: string, value: string) {
    setForm((current) => current ? {
      ...current,
      storage_env: { ...current.storage_env, [key]: value },
    } : current)
  }

  function updateVectorKwarg(key: string, value: unknown) {
    setForm((current) => {
      if (!current) return current
      const nextKwargs = { ...current.vector_db_storage_cls_kwargs }
      if (value === '' || value === null || value === undefined) {
        delete nextKwargs[key]
      } else {
        nextKwargs[key] = value
      }
      return { ...current, vector_db_storage_cls_kwargs: nextKwargs }
    })
  }

  function updateStorageClass(layer: StorageLayerKey, className: string) {
    setForm((current) => {
      if (!current) return current
      const next = {
        ...current,
        [storageFieldForLayer(layer)]: className,
      }
      return {
        ...next,
        storage_env: ensureStorageEnvDefaults(next.storage_env, requiredConnectionGroups(next)),
      }
    })
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
      base_url: meta?.baseUrl ?? '',
      api_key: '',
      api_key_configured: false,
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
        profile_id: profile.id,
        base_url: effectiveBaseUrl(channel) || null,
        api_key: channel.api_key || null,
        kind,
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
        base_url: effectiveBaseUrl(channel) || null,
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

  async function handleStorageTest(group: StorageConnectionGroupKey) {
    if (!form) return
    setStorageTests((prev) => ({ ...prev, [group]: { status: 'pending' } }))
    try {
      const result = await testStorageConnection({
        group,
        storage_env: buildStorageEnvForGroup(form, group),
      })
      setStorageTests((prev) => ({
        ...prev,
        [group]: result.ok
          ? { status: 'ok', latency: result.latency_ms }
          : { status: 'error', error: result.error ?? 'Connection failed' },
      }))
    } catch (err) {
      setStorageTests((prev) => ({
        ...prev,
        [group]: { status: 'error', error: err instanceof Error ? err.message : String(err) },
      }))
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (form && !storagePresetForForm(form)) return
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
  const localStorageState = localStorageUsage(form)
  const currentStoragePreset = storagePresetForForm(form)
  const storageComboError = currentStoragePreset ? null : unsupportedStorageMessage(form)

  return (
    <section className="page settings-page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Model profiles, credentials, directories, and processing defaults</p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={() => setForm(makeForm(settings))}>
            <RotateCcw size={16} /> Reset
          </button>
          <button
            className="button primary"
            form="studio-settings-form"
            disabled={saveMutation.isPending || Boolean(storageComboError)}
            title={storageComboError ?? undefined}
          >
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
          <button className={activePanel === 'storage' ? 'active' : ''} onClick={() => setActivePanel('storage')} type="button">
            <Database size={16} /> Storage
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
                    <p>{profileReady(selectedProfile) ? 'Ready for RAG selection' : profileSetupMessage(selectedProfile)}</p>
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
                      <span className={channelReady(selectedProfile[kind]) ? 'tab-dot ok' : 'tab-dot'} />
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
                <div className="storage-panel-header">
                  <div>
                    <h2>Studio Workspace</h2>
                    <p>Local files used by the Studio shell for uploads, parser output, and settings.</p>
                  </div>
                  <span className="storage-current-pill">runtime</span>
                </div>
                <DirPickerRow label="Data directory" value={form.data_dir} onChange={(v) => updateField('data_dir', v)} />
                <DirPickerRow label="Upload directory" value={form.upload_dir} onChange={(v) => updateField('upload_dir', v)} />
                <DirPickerRow label="Output directory" value={form.output_dir} onChange={(v) => updateField('output_dir', v)} />
                <label className="dir-picker-label">
                  Settings file
                  <input className="dir-picker-input" value={settings.settings_file} readOnly />
                </label>
              </div>
              <div className="panel stack">
                <h2>Environment</h2>
                {environment ? (
                  <>
                    <div className="setting-row">
                      <span>Python</span>
                      <strong>{environment.python}</strong>
                    </div>
                    <EnvDepRow label="RAG-Anything" available={environment.raganything_installed} />
                    <EnvDepRow label="LightRAG" available={environment.lightrag_installed} />
                    <EnvDepRow label="MinerU" available={environment.mineru_available} pkg="mineru[core]" />
                    <EnvDepRow label="Docling" available={environment.docling_available} pkg="docling" />
                    <EnvDepRow label="PaddleOCR" available={environment.paddleocr_available} pkg="paddleocr" />
                    <EnvDepRow label="LibreOffice" available={environment.libreoffice_available} note="Install via system package manager (apt / brew)" />
                    <CudaEnvRow gpuPresent={environment.cuda_gpu_present} cudaAvailable={environment.cuda_available} />
                  </>
                ) : (
                  <div className="empty">Loading…</div>
                )}
              </div>
            </div>
          )}

          {activePanel === 'storage' && (
            <div className="panel stack compact-settings storage-settings-panel">
              <div className="storage-panel-header">
                <div>
                  <h2>Storage Backends</h2>
                  <p>Choose storage for KV metadata, vectors, graph, and document status. Each dropdown only shows options that still form a supported LightRAG layout.</p>
                </div>
                <span className="storage-current-pill">{currentStoragePreset?.label ?? 'Unsupported'}</span>
              </div>

              {storageComboError ? (
                <div className="storage-combo-warning">
                  <AlertTriangle size={15} />
                  <span>{storageComboError}</span>
                </div>
              ) : null}

              <div className="storage-class-summary">
                {(['kv', 'vector', 'graph', 'docStatus'] as StorageLayerKey[]).map((layer) => {
                  const currentOption = optionForClass(layer, storageClassForLayer(form, layer))
                  const options = validLayerOptions(form, layer)
                  return (
                    <label className="storage-layer-card" key={layer}>
                      <span>{STORAGE_LAYER_LABELS[layer]}</span>
                      <select
                        value={storageClassForLayer(form, layer)}
                        onChange={(event) => updateStorageClass(layer, event.target.value)}
                      >
                        {options.map((option) => (
                          <option key={option.className} value={option.className}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <small>{currentOption.className}</small>
                      <em>{currentOption.description}</em>
                    </label>
                  )
                })}
              </div>

              <div className="storage-preset-grid">
                {(Object.keys(STORAGE_PRESETS) as StoragePresetKey[]).map((key) => {
                  const preset = STORAGE_PRESETS[key]
                  const active = currentStoragePreset === preset
                  return (
                    <button
                      className={`storage-preset-card ${active ? 'active' : ''}`}
                      key={key}
                      type="button"
                      onClick={() => applyStoragePreset(key)}
                    >
                      <strong>{preset.label}</strong>
                      <span>{preset.description}</span>
                    </button>
                  )
                })}
              </div>

              <div className="storage-vector-panel">
                <div>
                  <h3>Vector retrieval</h3>
                  <p>Optional LightRAG vector search tuning without exposing raw kwargs.</p>
                </div>
                <label>
                  Cosine threshold
                  <input
                    min={0}
                    max={1}
                    step={0.01}
                    type="number"
                    value={kwargNumber(form.vector_db_storage_cls_kwargs, 'cosine_better_than_threshold')}
                    onChange={(e) => updateVectorKwarg(
                      'cosine_better_than_threshold',
                      e.target.value === '' ? undefined : Number(e.target.value),
                    )}
                    placeholder="Backend default"
                  />
                </label>
              </div>

              <StorageConnectionForms
                form={form}
                testStates={storageTests}
                onChange={updateStorageEnv}
                onTest={handleStorageTest}
              />

              {localStorageState.usesLocal ? (
                <div className="local-storage-workspace">
                  <div>
                    <h3>Local Storage Workspace</h3>
                    <p>{localStorageState.reason}</p>
                  </div>
                  <DirPickerRow label="Working directory" value={form.working_dir} onChange={(v) => updateField('working_dir', v)} />
                </div>
              ) : (
                <div className="external-storage-note">
                  <strong>External storage mode</strong>
                  <span>Primary RAG indexes are resolved through the configured backend classes and environment settings.</span>
                </div>
              )}
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
                    {environment?.cuda_available ? (
                      <>
                        <option value="cuda">cuda</option>
                        <option value="cuda:0">cuda:0</option>
                      </>
                    ) : null}
                    {environment?.mps_available ? (
                      <option value="mps">mps (Apple Silicon)</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Concurrent files
                  <input
                    min={1}
                    max={32}
                    type="number"
                    value={form.max_concurrent_files}
                    onChange={(e) => updateField('max_concurrent_files', Number(e.target.value))}
                  />
                </label>
              </div>
              <label className="inline-check">
                <input
                  checked={form.default_enable_vlm_enhancement}
                  type="checkbox"
                  onChange={(e) => updateField('default_enable_vlm_enhancement', e.target.checked)}
                />
                Enable VLM enhancement by default
              </label>
              <h2>Performance Layer</h2>
              <div className="form-grid">
                <label>
                  Processing preset
                  <select
                    value={form.default_processing_preset}
                    onChange={(e) => updateField('default_processing_preset', e.target.value as ProcessingPreset)}
                  >
                    <option value="fast">Fast</option>
                    <option value="balanced">Balanced</option>
                    <option value="deep">Deep</option>
                    <option value="custom">Custom</option>
                  </select>
                </label>
                <label>
                  Embedding batch
                  <input
                    min={1}
                    max={1024}
                    type="number"
                    value={form.embedding_batch_size}
                    onChange={(e) => updateField('embedding_batch_size', Number(e.target.value))}
                  />
                </label>
                <label>
                  LLM concurrency
                  <input
                    min={1}
                    max={64}
                    type="number"
                    value={form.llm_max_concurrency}
                    onChange={(e) => updateField('llm_max_concurrency', Number(e.target.value))}
                  />
                </label>
                <label>
                  VLM concurrency
                  <input
                    min={1}
                    max={64}
                    type="number"
                    value={form.vlm_max_concurrency}
                    onChange={(e) => updateField('vlm_max_concurrency', Number(e.target.value))}
                  />
                </label>
                <label>
                  Embedding concurrency
                  <input
                    min={1}
                    max={128}
                    type="number"
                    value={form.embedding_max_concurrency}
                    onChange={(e) => updateField('embedding_max_concurrency', Number(e.target.value))}
                  />
                </label>
                <label>
                  Retry attempts
                  <input
                    min={1}
                    max={10}
                    type="number"
                    value={form.retry_max_attempts}
                    onChange={(e) => updateField('retry_max_attempts', Number(e.target.value))}
                  />
                </label>
                <label>
                  Retry base delay
                  <input
                    min={0}
                    max={60}
                    step={0.1}
                    type="number"
                    value={form.retry_base_delay}
                    onChange={(e) => updateField('retry_base_delay', Number(e.target.value))}
                  />
                </label>
                <label>
                  Retry max delay
                  <input
                    min={0}
                    max={300}
                    step={0.1}
                    type="number"
                    value={form.retry_max_delay}
                    onChange={(e) => updateField('retry_max_delay', Number(e.target.value))}
                  />
                </label>
              </div>
              <div className="toggle-row">
                <label>
                  <input checked={form.default_enable_parse_cache} type="checkbox" onChange={(e) => updateField('default_enable_parse_cache', e.target.checked)} />
                  Parse cache
                </label>
                <label>
                  <input checked={form.default_enable_modal_cache} type="checkbox" onChange={(e) => updateField('default_enable_modal_cache', e.target.checked)} />
                  Modal cache
                </label>
                <label>
                  <input checked={form.default_preview_mode} type="checkbox" onChange={(e) => updateField('default_preview_mode', e.target.checked)} />
                  Preview mode
                </label>
                <label>
                  <input checked={form.write_lock_enabled} type="checkbox" onChange={(e) => updateField('write_lock_enabled', e.target.checked)} />
                  Working-dir write lock
                </label>
              </div>
              {environment?.cuda_gpu_present && !environment.cuda_available ? (
                <div className="cuda-install-hint">
                  <AlertTriangle size={14} />
                  <span>NVIDIA GPU detected but CUDA is not available. Install PyTorch with CUDA support to enable GPU acceleration.</span>
                  <a href="https://pytorch.org/get-started/locally/" target="_blank" rel="noreferrer" className="button">
                    <Download size={13} /> PyTorch install guide
                  </a>
                </div>
              ) : null}
            </div>
          )}

          {saveMutation.error ? <div className="error-panel">{saveMutation.error.message}</div> : null}
          {storageComboError ? <div className="error-panel">{storageComboError}</div> : null}
          {saveMutation.isSuccess ? <div className="success-panel">Settings saved</div> : null}
        </form>
      </div>
    </section>
  )
}

function DirPickerRow({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false)

  return (
    <label className="dir-picker-label" onClick={(e) => e.preventDefault()}>
      {label}
      <div className="dir-picker-row">
        <input
          className="dir-picker-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="/path/to/directory"
        />
        <button type="button" className="button dir-browse-btn" onClick={() => setOpen(true)} title="Browse filesystem">
          <FolderOpen size={14} />
        </button>
      </div>
      {open ? (
        <DirBrowserModal
          initialPath={value}
          onSelect={(path) => { onChange(path); setOpen(false) }}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </label>
  )
}

function DirBrowserModal({ initialPath, onSelect, onClose }: {
  initialPath: string
  onSelect: (path: string) => void
  onClose: () => void
}) {
  const [currentPath, setCurrentPath] = useState(initialPath || '')
  const [entries, setEntries] = useState<BrowseDirEntry[]>([])
  const [resolvedPath, setResolvedPath] = useState('')
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    navigate(currentPath)
  }, [])

  async function navigate(path: string) {
    setLoading(true)
    setError(null)
    try {
      const result = await browseDir(path)
      setResolvedPath(result.path)
      setParentPath(result.parent)
      setEntries(result.entries)
      setCurrentPath(result.path)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="dir-modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dir-modal">
        <div className="dir-modal-header">
          <span className="dir-modal-path" title={resolvedPath}>{resolvedPath || '…'}</span>
          <button type="button" className="icon-button" onClick={onClose}><XCircle size={16} /></button>
        </div>

        <div className="dir-modal-body">
          {loading ? (
            <div className="dir-modal-status"><Loader2 size={16} className="spin" /> Loading…</div>
          ) : error ? (
            <div className="dir-modal-status dir-modal-error">{error}</div>
          ) : (
            <div className="dir-entry-list">
              {parentPath !== null ? (
                <button type="button" className="dir-entry dir-entry--up" onClick={() => navigate(parentPath!)}>
                  <FolderOpen size={14} /> ..
                </button>
              ) : null}
              {entries.filter((e) => e.is_dir).map((entry) => (
                <button
                  key={entry.path}
                  type="button"
                  className="dir-entry"
                  onClick={() => navigate(entry.path)}
                >
                  <FolderOpen size={14} />
                  <span>{entry.name}</span>
                </button>
              ))}
              {entries.filter((e) => e.is_dir).length === 0 && !loading ? (
                <div className="dir-modal-status">No subdirectories</div>
              ) : null}
            </div>
          )}
        </div>

        <div className="dir-modal-footer">
          <span className="dir-modal-selection">{resolvedPath}</span>
          <button type="button" className="button primary" onClick={() => onSelect(resolvedPath)} disabled={!resolvedPath}>
            Select
          </button>
        </div>
      </div>
    </div>
  )
}

type InstallStatus = 'idle' | 'installing' | 'done' | 'error'

function EnvDepRow({ label, available, pkg, note }: {
  label: string
  available: boolean
  pkg?: string
  note?: string
}) {
  const [status, setStatus] = useState<InstallStatus>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  async function handleInstall() {
    if (!pkg) return
    setStatus('installing')
    setErrorMsg(null)
    try {
      const result = await installDep({ package: pkg })
      if (result.ok) {
        setStatus('done')
      } else {
        setStatus('error')
        setErrorMsg(result.error ?? 'Installation failed')
      }
    } catch (err) {
      setStatus('error')
      setErrorMsg(err instanceof Error ? err.message : String(err))
    }
  }

  const effectivelyAvailable = available || status === 'done'

  return (
    <div className="env-dep-row">
      <span className="env-dep-label">{label}</span>
      {effectivelyAvailable ? (
        <span className="env-badge env-badge--ok">available</span>
      ) : note ? (
        <span className="env-badge env-badge--note" title={note}>system pkg</span>
      ) : pkg ? (
        <div className="env-dep-actions">
          {status === 'error' && errorMsg ? (
            <span className="env-dep-error" title={errorMsg}><XCircle size={12} /> failed</span>
          ) : (
            <>
              <span className="env-badge env-badge--missing">missing</span>
              <button
                type="button"
                className="button env-install-btn"
                disabled={status === 'installing'}
                onClick={handleInstall}
              >
                {status === 'installing'
                  ? <><Loader2 size={12} className="spin" /> Installing…</>
                  : <><Download size={12} /> Install</>}
              </button>
            </>
          )}
        </div>
      ) : (
        <span className="env-badge env-badge--missing">missing</span>
      )}
    </div>
  )
}

function CudaEnvRow({ gpuPresent, cudaAvailable }: { gpuPresent: boolean; cudaAvailable: boolean }) {
  if (cudaAvailable) {
    return (
      <div className="env-dep-row">
        <span className="env-dep-label">CUDA</span>
        <span className="env-badge env-badge--ok">available</span>
      </div>
    )
  }
  if (!gpuPresent) {
    return (
      <div className="env-dep-row">
        <span className="env-dep-label">CUDA</span>
        <span className="env-badge env-badge--na">N/A (no NVIDIA GPU)</span>
      </div>
    )
  }
  return (
    <div className="env-dep-row env-dep-row--cuda-warn">
      <span className="env-dep-label">CUDA</span>
      <div className="env-dep-actions">
        <span className="env-badge env-badge--warn">GPU found, CUDA missing</span>
        <a
          href="https://pytorch.org/get-started/locally/"
          target="_blank"
          rel="noreferrer"
          className="button env-install-btn"
        >
          <Download size={12} /> Setup guide
        </a>
      </div>
    </div>
  )
}

function StorageConnectionForms({ form, testStates, onChange, onTest }: {
  form: SettingsForm
  testStates: Record<string, TestState>
  onChange: (key: string, value: string) => void
  onTest: (group: StorageConnectionGroupKey) => void
}) {
  const groups = requiredConnectionGroups(form)
  if (groups.length === 0) return null

  return (
    <div className="storage-connection-stack">
      {groups.map((groupKey) => {
        const group = STORAGE_CONNECTION_GROUPS[groupKey]
        return (
          <section className="storage-connection-panel" key={groupKey}>
            <div className="storage-connection-header">
              <div>
                <h3>{group.label}</h3>
                <p>{group.description}</p>
              </div>
              <div className="storage-connection-actions">
                <span>{groupKey}</span>
                <button
                  className="button test-btn"
                  disabled={testStates[groupKey]?.status === 'pending'}
                  onClick={() => onTest(groupKey)}
                  type="button"
                >
                  {testStates[groupKey]?.status === 'pending'
                    ? <><Loader2 size={13} className="spin" /> Testing...</>
                    : <><Zap size={13} /> Test connection</>}
                </button>
              </div>
            </div>
            <div className="storage-connection-grid">
              {group.fields.map((field) => {
                const configured = form.storage_env_configured[field.key]
                const value = form.storage_env[field.key] ?? ''
                const commonProps = {
                  value,
                  onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => (
                    onChange(field.key, event.target.value)
                  ),
                }
                return (
                  <label key={field.key}>
                    {field.label}
                    {field.type === 'select' ? (
                      <select {...commonProps}>
                        {(field.options ?? []).map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        {...commonProps}
                        type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
                        placeholder={
                          field.type === 'password' && configured
                            ? '••••••••••••'
                            : field.placeholder
                        }
                      />
                    )}
                    {field.type === 'password' && configured && !value ? (
                      <span className="field-hint">Saved value will be kept unless you enter a replacement.</span>
                    ) : null}
                  </label>
                )
              })}
            </div>
            <StorageTestResult state={testStates[groupKey] ?? idleTest} />
          </section>
        )
      })}
    </div>
  )
}

function StorageTestResult({ state }: { state: TestState }) {
  if (state.status === 'idle' || state.status === 'pending') return null
  if (state.status === 'ok') {
    return (
      <div className="storage-test-result storage-test-result--ok">
        <CheckCircle2 size={13} />
        <span>{state.latency != null ? `Connected in ${state.latency} ms` : 'Connected'}</span>
      </div>
    )
  }
  return (
    <div className="storage-test-result storage-test-result--error" title={state.error ?? undefined}>
      <XCircle size={13} />
      <span>{state.error ? summarizeProviderError(state.error) : 'Connection failed'}</span>
    </div>
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
  const authOptional = providerApiKeyOptional(channel.provider)
  const isEditableBaseUrl = !meta?.baseUrl || authOptional
  const configured = channel.api_key_configured || Boolean(channel.api_key)
  const secretClass = configured
    ? 'secret-state configured'
    : authOptional
      ? 'secret-state optional'
      : 'secret-state'
  const secretLabel = configured ? 'Key saved' : authOptional ? 'Key optional' : 'No key'

  return (
    <div className="panel stack provider-panel">
      <div className="provider-header">
        <h2>{title}</h2>
        <span className={secretClass}>{secretLabel}</span>
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

      {isEditableBaseUrl ? (
        <label>
          Base URL
          <input
            value={channel.base_url}
            onChange={(e) => onBaseUrl(e.target.value)}
            placeholder={meta?.baseUrl || 'https://.../v1'}
          />
          {meta?.local ? (
            <span className="field-hint">Use the local default or replace it with the LAN/remote service URL.</span>
          ) : null}
        </label>
      ) : (
        <div className="setting-row base-url-display">
          <span className="base-url-label">Base URL</span>
          <span className="base-url-value">{meta.baseUrl}</span>
        </div>
      )}

      {authOptional ? (
        <div className="local-provider-note">
          <ServerCog size={15} />
          <span>
            OpenAI-compatible local endpoints can run without a cloud API key. Use Test connection after the service is running.
          </span>
        </div>
      ) : null}

      <label>
        {authOptional ? 'API key (optional)' : 'API key'}
        <input
          type="password"
          value={channel.api_key}
          placeholder={channel.api_key_configured ? '••••••••••••••••' : authOptional ? 'Optional token...' : 'Enter API key...'}
          onChange={(e) => onApiKey(e.target.value)}
        />
        {channel.api_key_configured && !channel.api_key ? (
          <span className="field-hint">Saved key will be kept unless you enter a replacement.</span>
        ) : authOptional ? (
          <span className="field-hint">Leave blank for Ollama, LM Studio, vLLM, or any local endpoint that does not require auth.</span>
        ) : null}
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
  const form: SettingsForm = {
    data_dir: settings.data_dir,
    upload_dir: settings.upload_dir,
    working_dir: settings.working_dir,
    output_dir: settings.output_dir,
    default_parser: settings.default_parser,
    default_parse_method: settings.default_parse_method,
    default_language: settings.default_language,
    default_device: settings.default_device,
    default_enable_vlm_enhancement: settings.default_enable_vlm_enhancement,
    max_concurrent_files: settings.max_concurrent_files,
    default_processing_preset: settings.default_processing_preset,
    default_enable_parse_cache: settings.default_enable_parse_cache,
    default_enable_modal_cache: settings.default_enable_modal_cache,
    default_preview_mode: settings.default_preview_mode,
    embedding_batch_size: settings.embedding_batch_size,
    llm_max_concurrency: settings.llm_max_concurrency,
    vlm_max_concurrency: settings.vlm_max_concurrency,
    embedding_max_concurrency: settings.embedding_max_concurrency,
    retry_max_attempts: settings.retry_max_attempts,
    retry_base_delay: settings.retry_base_delay,
    retry_max_delay: settings.retry_max_delay,
    write_lock_enabled: settings.write_lock_enabled,
    kv_storage: settings.kv_storage,
    vector_storage: settings.vector_storage,
    graph_storage: settings.graph_storage,
    doc_status_storage: settings.doc_status_storage,
    vector_db_storage_cls_kwargs: settings.vector_db_storage_cls_kwargs ?? {},
    storage_env: settings.storage_env ?? {},
    storage_env_configured: settings.storage_env_configured ?? {},
    active_profile_id: settings.active_profile_id || profiles[0].id,
    profiles,
  }
  return {
    ...form,
    storage_env: ensureStorageEnvDefaults(form.storage_env, requiredConnectionGroups(form)),
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
  const vectorDbStorageClsKwargs = cleanRecord(form.vector_db_storage_cls_kwargs)
  const storageEnv = buildStorageEnvPayload(form)
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
    default_enable_vlm_enhancement: form.default_enable_vlm_enhancement,
    max_concurrent_files: form.max_concurrent_files,
    default_processing_preset: form.default_processing_preset,
    default_enable_parse_cache: form.default_enable_parse_cache,
    default_enable_modal_cache: form.default_enable_modal_cache,
    default_preview_mode: form.default_preview_mode,
    embedding_batch_size: form.embedding_batch_size,
    llm_max_concurrency: form.llm_max_concurrency,
    vlm_max_concurrency: form.vlm_max_concurrency,
    embedding_max_concurrency: form.embedding_max_concurrency,
    retry_max_attempts: form.retry_max_attempts,
    retry_base_delay: form.retry_base_delay,
    retry_max_delay: form.retry_max_delay,
    write_lock_enabled: form.write_lock_enabled,
    kv_storage: form.kv_storage,
    vector_storage: form.vector_storage,
    graph_storage: form.graph_storage,
    doc_status_storage: form.doc_status_storage,
    vector_db_storage_cls_kwargs: vectorDbStorageClsKwargs,
    storage_env: storageEnv,
    active_profile_id: form.active_profile_id,
    profiles: form.profiles.map(profileToPayload),
  }
}

function localStorageUsage(form: SettingsForm) {
  const localClasses = (['kv', 'vector', 'graph', 'docStatus'] as StorageLayerKey[])
    .map((layer) => storageClassForLayer(form, layer))
    .filter((name) => [
      'JsonKVStorage',
      'NanoVectorDBStorage',
      'FaissVectorDBStorage',
      'NetworkXStorage',
      'JsonDocStatusStorage',
    ].includes(name))
  return {
    usesLocal: localClasses.length > 0,
    reason: localClasses.length > 0
      ? `${localClasses.join(', ')} use this directory for local indexes or metadata.`
      : 'No selected storage class requires a local index workspace.',
  }
}

function storageFieldForLayer(layer: StorageLayerKey): keyof Pick<
  SettingsForm,
  'kv_storage' | 'vector_storage' | 'graph_storage' | 'doc_status_storage'
> {
  if (layer === 'kv') return 'kv_storage'
  if (layer === 'vector') return 'vector_storage'
  if (layer === 'graph') return 'graph_storage'
  return 'doc_status_storage'
}

function storageClassForLayer(form: SettingsForm, layer: StorageLayerKey): string {
  return form[storageFieldForLayer(layer)]
}

function optionForClass(layer: StorageLayerKey, className: string): StorageLayerOption {
  return STORAGE_LAYER_OPTIONS[layer].find((option) => option.className === className)
    ?? STORAGE_LAYER_OPTIONS[layer][0]
}

function validLayerOptions(form: SettingsForm, layer: StorageLayerKey): StorageLayerOption[] {
  const validClassNames = new Set(
    supportedStoragePresetsForLayer(form, layer)
      .map((preset) => storageClassFromPreset(preset, layer)),
  )
  const options = STORAGE_LAYER_OPTIONS[layer].filter((option) => (
    option.className === storageClassForLayer(form, layer)
    || validClassNames.has(option.className)
  ))
  return options.length > 0 ? uniqueStorageOptions(options) : STORAGE_LAYER_OPTIONS[layer]
}

function supportedStoragePresetsForLayer(form: SettingsForm, layer: StorageLayerKey): StoragePreset[] {
  return (Object.keys(STORAGE_PRESETS) as StoragePresetKey[])
    .map((key) => STORAGE_PRESETS[key])
    .filter((preset) => (
      layer === 'kv' || form.kv_storage === preset.kv_storage
    ))
    .filter((preset) => (
      layer === 'vector' || form.vector_storage === preset.vector_storage
    ))
    .filter((preset) => (
      layer === 'graph' || form.graph_storage === preset.graph_storage
    ))
    .filter((preset) => (
      layer === 'docStatus' || form.doc_status_storage === preset.doc_status_storage
    ))
}

function uniqueStorageOptions(options: StorageLayerOption[]): StorageLayerOption[] {
  const seen = new Set<string>()
  return options.filter((option) => {
    if (seen.has(option.className)) return false
    seen.add(option.className)
    return true
  })
}

function storageClassFromPreset(preset: StoragePreset, layer: StorageLayerKey): string {
  if (layer === 'kv') return preset.kv_storage
  if (layer === 'vector') return preset.vector_storage
  if (layer === 'graph') return preset.graph_storage
  return preset.doc_status_storage
}

function requiredConnectionGroups(form: SettingsForm): StorageConnectionGroupKey[] {
  const groups = new Set<StorageConnectionGroupKey>()
  for (const layer of ['kv', 'vector', 'graph', 'docStatus'] as StorageLayerKey[]) {
    const group = optionForClass(layer, storageClassForLayer(form, layer)).connectionGroup
    if (group) groups.add(group)
  }
  return [...groups]
}

function ensureStorageEnvDefaults(
  current: Record<string, string>,
  groups: StorageConnectionGroupKey[],
): Record<string, string> {
  const next = { ...current }
  for (const group of groups) {
    for (const field of STORAGE_CONNECTION_GROUPS[group].fields) {
      if (next[field.key] == null) {
        next[field.key] = STORAGE_ENV_DEFAULTS[field.key] ?? ''
      }
    }
  }
  return next
}

function buildStorageEnvPayload(form: SettingsForm): Record<string, string> {
  const env: Record<string, string> = {}
  for (const group of requiredConnectionGroups(form)) {
    Object.assign(env, buildStorageEnvForGroup(form, group))
  }
  return env
}

function buildStorageEnvForGroup(
  form: SettingsForm,
  group: StorageConnectionGroupKey,
): Record<string, string> {
  const env: Record<string, string> = {}
  for (const field of STORAGE_CONNECTION_GROUPS[group].fields) {
    const value = form.storage_env[field.key] ?? ''
    if (value || form.storage_env_configured[field.key] || STORAGE_ENV_DEFAULTS[field.key] != null) {
      env[field.key] = value
    }
  }
  return env
}

function storagePresetForForm(form: SettingsForm): StoragePreset | null {
  return (Object.keys(STORAGE_PRESETS) as StoragePresetKey[])
    .map((key) => STORAGE_PRESETS[key])
    .find((preset) => (
      form.kv_storage === preset.kv_storage
      && form.vector_storage === preset.vector_storage
      && form.graph_storage === preset.graph_storage
      && form.doc_status_storage === preset.doc_status_storage
    )) ?? null
}

function unsupportedStorageMessage(form: SettingsForm): string {
  return [
    'Unsupported storage combination:',
    form.kv_storage,
    form.vector_storage,
    form.graph_storage,
    form.doc_status_storage,
  ].join(' ')
}

function kwargNumber(kwargs: Record<string, unknown>, key: string): number | '' {
  const value = kwargs[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : ''
}

function cleanRecord(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).filter(([, val]) => val !== '' && val !== null && val !== undefined),
  )
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
  return channelReady(profile.llm) && channelReady(profile.embedding)
}

function profileSetupMessage(profile: ProfileForm) {
  const missing: string[] = []
  if (!channelReady(profile.llm)) missing.push('LLM')
  if (!channelReady(profile.embedding)) missing.push('Embedding')
  if (missing.length === 0) return 'Ready for RAG selection'
  return `${missing.join(' and ')} model, endpoint, or credentials need attention`
}

function channelReady(channel: ChannelForm) {
  return Boolean(
    channel.model
    && effectiveBaseUrl(channel)
    && (providerApiKeyOptional(channel.provider) || channel.api_key_configured || channel.api_key),
  )
}

function effectiveBaseUrl(channel: Pick<ChannelForm, 'provider' | 'base_url'>) {
  return channel.base_url || KNOWN_PROVIDERS[channel.provider]?.baseUrl || ''
}

function providerApiKeyOptional(provider: string) {
  return KNOWN_PROVIDERS[provider]?.auth === 'optional'
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
