export const SYSTEM_DATA_EPOCH_KEY = 'raganything_system_data_epoch'

const LEGACY_KEYS = new Set(['autorepair_kb', 'mfg_kb'])

function storageKeys(storage) {
  const keys = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (key) keys.push(key)
  }
  return keys
}

function isApplicationKey(key) {
  return key.startsWith('raganything_')
    || key.startsWith('raganything:')
    || LEGACY_KEYS.has(key)
}

export function applySystemDataEpoch(
  epoch,
  local = globalThis.localStorage,
  session = globalThis.sessionStorage,
) {
  const normalized = String(epoch || '').trim()
  if (!normalized || !local || !session) return false
  if (local.getItem(SYSTEM_DATA_EPOCH_KEY) === normalized) return false

  for (const key of storageKeys(local)) {
    if (key !== SYSTEM_DATA_EPOCH_KEY && isApplicationKey(key)) {
      local.removeItem(key)
    }
  }
  for (const key of storageKeys(session)) {
    if (isApplicationKey(key)) session.removeItem(key)
  }
  local.setItem(SYSTEM_DATA_EPOCH_KEY, normalized)
  return true
}

export async function synchronizeSystemDataEpoch({
  fetchImpl = globalThis.fetch,
  local = globalThis.localStorage,
  session = globalThis.sessionStorage,
  timeoutMs = 3000,
} = {}) {
  if (typeof fetchImpl !== 'function') return false
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl('/api/health', {
      cache: 'no-store',
      signal: controller.signal,
    })
    if (!response.ok) return false
    const payload = await response.json()
    return applySystemDataEpoch(payload.system_data_epoch, local, session)
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

export function startSystemDataEpochMonitor({
  intervalMs = 15000,
  onReset = () => globalThis.location?.reload(),
  target = globalThis.window,
  documentTarget = globalThis.document,
  synchronize = synchronizeSystemDataEpoch,
} = {}) {
  let stopped = false
  let checking = false

  const check = async () => {
    if (stopped || checking) return
    checking = true
    try {
      if (await synchronize()) onReset()
    } finally {
      checking = false
    }
  }
  const handleStorage = event => {
    if (
      event.key === SYSTEM_DATA_EPOCH_KEY
      && event.newValue
      && event.newValue !== event.oldValue
    ) {
      onReset()
    }
  }
  const handleVisibility = () => {
    if (!documentTarget || documentTarget.visibilityState === 'visible') check()
  }

  target?.addEventListener?.('focus', check)
  target?.addEventListener?.('storage', handleStorage)
  documentTarget?.addEventListener?.('visibilitychange', handleVisibility)
  const timer = intervalMs > 0 ? setInterval(check, intervalMs) : null

  return () => {
    stopped = true
    if (timer) clearInterval(timer)
    target?.removeEventListener?.('focus', check)
    target?.removeEventListener?.('storage', handleStorage)
    documentTarget?.removeEventListener?.('visibilitychange', handleVisibility)
  }
}
