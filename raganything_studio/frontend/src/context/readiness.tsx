import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getDocuments, getStudioSettings } from '../api/client'
import type { ModelChannel } from '../types/studio'

export interface ReadinessState {
  llmReady: boolean
  embeddingReady: boolean
  indexedCount: number
  isLoading: boolean
  /** Both LLM and embedding channels are usable */
  fullyConfigured: boolean
}

const ReadinessContext = createContext<ReadinessState>({
  llmReady: false,
  embeddingReady: false,
  indexedCount: 0,
  isLoading: true,
  fullyConfigured: false,
})

export function ReadinessProvider({ children }: { children: ReactNode }) {
  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: getStudioSettings,
    staleTime: 30_000,
  })

  const { data: documents = [], isLoading: docsLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: getDocuments,
    staleTime: 10_000,
  })

  const activeProfile = settings?.profiles.find((profile) => profile.id === settings.active_profile_id)
  const llmReady = activeProfile
    ? channelReady(activeProfile.llm)
    : legacyChannelReady(settings?.llm_provider, settings?.llm_model, settings?.llm_base_url, settings?.llm_api_key_configured)
  const embeddingReady = activeProfile
    ? channelReady(activeProfile.embedding)
    : legacyChannelReady(
        settings?.embedding_provider,
        settings?.embedding_model,
        settings?.embedding_base_url,
        settings?.embedding_api_key_configured,
      )
  const indexedCount = documents.filter((d) => d.status === 'indexed').length

  const value: ReadinessState = {
    llmReady,
    embeddingReady,
    indexedCount,
    isLoading: settingsLoading || docsLoading,
    fullyConfigured: llmReady && embeddingReady,
  }

  return <ReadinessContext.Provider value={value}>{children}</ReadinessContext.Provider>
}

export function useReadiness() {
  return useContext(ReadinessContext)
}

const KEY_OPTIONAL_PROVIDERS = new Set(['ollama', 'lmstudio', 'vllm', 'openai-compatible', 'custom'])

const PROVIDER_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  siliconflow: 'https://api.siliconflow.cn/v1',
  'aliyun-bailian': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  'baidu-qianfan': 'https://qianfan.baidubce.com/v2',
  volcengine: 'https://ark.cn-beijing.volces.com/api/v3',
  openrouter: 'https://openrouter.ai/api/v1',
  deepseek: 'https://api.deepseek.com/v1',
  zhipu: 'https://open.bigmodel.cn/api/paas/v4',
  moonshot: 'https://api.moonshot.cn/v1',
  groq: 'https://api.groq.com/openai/v1',
  together: 'https://api.together.xyz/v1',
  mistral: 'https://api.mistral.ai/v1',
  ollama: 'http://localhost:11434/v1',
  lmstudio: 'http://localhost:1234/v1',
  vllm: 'http://localhost:8000/v1',
}

function channelReady(channel: ModelChannel) {
  return legacyChannelReady(channel.provider, channel.model, channel.base_url, channel.api_key_configured)
}

function legacyChannelReady(
  provider?: string,
  model?: string,
  baseUrl?: string | null,
  keyConfigured?: boolean,
) {
  if (!provider || !model) return false
  return Boolean(
    (baseUrl || PROVIDER_BASE_URLS[provider])
    && (keyConfigured || KEY_OPTIONAL_PROVIDERS.has(provider)),
  )
}
