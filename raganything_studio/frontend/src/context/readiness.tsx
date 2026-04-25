import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getDocuments, getStudioSettings } from '../api/client'

export interface ReadinessState {
  llmReady: boolean
  embeddingReady: boolean
  indexedCount: number
  isLoading: boolean
  /** Both LLM and embedding keys are configured */
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
  const llmReady = activeProfile?.llm.api_key_configured ?? settings?.llm_api_key_configured ?? false
  const embeddingReady = activeProfile?.embedding.api_key_configured
    ?? settings?.embedding_api_key_configured
    ?? false
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
