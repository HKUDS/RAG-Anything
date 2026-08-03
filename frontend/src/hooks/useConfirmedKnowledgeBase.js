import { useCallback, useEffect, useState } from 'react'

import { api, setCurrentKB } from '../utils/api'
import { isKnowledgeBaseConfirmed } from '../utils/confirmedKnowledgeBase'

export function useConfirmedKnowledgeBase(kbName) {
  const [reloadKey, setReloadKey] = useState(0)
  const [state, setState] = useState({ kbName, status: 'loading', error: null })

  useEffect(() => {
    let active = true
    setState({ kbName, status: 'loading', error: null })
    setCurrentKB('')

    api.listKBs({ force: reloadKey > 0 })
      .then(response => {
        if (!active) return
        if (isKnowledgeBaseConfirmed(response, kbName)) {
          setCurrentKB(kbName)
          setState({ kbName, status: 'ready', error: null })
          return
        }
        setState({ kbName, status: 'unavailable', error: null })
      })
      .catch(error => {
        if (!active) return
        if (error?.status === 403 || error?.status === 404) {
          setState({ kbName, status: 'unavailable', error: null })
          return
        }
        setState({ kbName, status: 'error', error })
      })

    return () => { active = false }
  }, [kbName, reloadKey])

  const retry = useCallback(() => setReloadKey(value => value + 1), [])
  const currentState = state.kbName === kbName ? state : { kbName, status: 'loading', error: null }
  return {
    confirmed: currentState.status === 'ready',
    loading: currentState.status === 'loading',
    unavailable: currentState.status === 'unavailable',
    error: currentState.error,
    retry,
  }
}
