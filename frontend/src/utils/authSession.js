export const AUTH_KEY = 'raganything_auth'

let refreshInFlight = null

export function readStoredAuth() {
  try {
    const raw = globalThis.localStorage?.getItem(AUTH_KEY)
    if (!raw) return null
    const value = JSON.parse(raw)
    if (!value || typeof value !== 'object') return null
    return value
  } catch {
    return null
  }
}

export function writeStoredAuth({ access_token, refresh_token, user }) {
  const value = {
    token: access_token,
    refreshToken: refresh_token,
    user: user || null,
  }
  globalThis.localStorage?.setItem(AUTH_KEY, JSON.stringify(value))
  return value
}

export function removeStoredAuth() {
  globalThis.localStorage?.removeItem(AUTH_KEY)
}

function dispatchAuthEvent(name, detail) {
  if (typeof globalThis.window?.dispatchEvent !== 'function') return
  const event = typeof globalThis.CustomEvent === 'function'
    ? new globalThis.CustomEvent(name, { detail })
    : { type: name, detail }
  globalThis.window.dispatchEvent(event)
}

async function readError(response, fallback) {
  try {
    const payload = await response.json()
    return payload?.detail || fallback
  } catch {
    return fallback
  }
}

export function refreshStoredSession(fetchImpl = globalThis.fetch) {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    const saved = readStoredAuth()
    if (!saved?.refreshToken) return null

    const response = await fetchImpl('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: saved.refreshToken }),
    })
    if (response.status === 401 || response.status === 403) return null
    if (!response.ok) {
      const error = new Error(await readError(response, '会话续期失败，请稍后重试'))
      error.status = response.status
      throw error
    }

    const refreshed = await response.json()
    if (!refreshed?.access_token || !refreshed?.refresh_token || !refreshed?.user) {
      throw new Error('服务器返回了无效的会话续期响应')
    }
    const stored = writeStoredAuth(refreshed)
    dispatchAuthEvent('raganything:auth-refreshed', {
      ...refreshed,
      stored,
    })
    return refreshed
  })().finally(() => {
    refreshInFlight = null
  })

  return refreshInFlight
}

export function notifyAuthExpired() {
  removeStoredAuth()
  dispatchAuthEvent('raganything:auth-expired')
}

export function resetRefreshStateForTests() {
  refreshInFlight = null
}
