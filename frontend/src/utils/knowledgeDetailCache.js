export const KNOWLEDGE_DETAIL_CACHE_TTL_MS = 30_000
export const KNOWLEDGE_DETAIL_CACHE_MAX_ENTRIES = 20

function requireKBName(kbName) {
  if (typeof kbName !== 'string' || !kbName) {
    throw new TypeError('A non-empty KB name is required')
  }
  return kbName
}

/**
 * Build an unambiguous key for an authenticated knowledge-base detail read.
 * The scope is deliberately part of the key so a later login cannot reuse
 * data fetched under an earlier authentication generation.
 */
export function knowledgeDetailCacheKey(authGeneration, kbName) {
  return JSON.stringify([authGeneration, requireKBName(kbName)])
}

/**
 * Small, dependency-free cache for document-summary and statistic payloads.
 *
 * Entries are intentionally memory-only. Callers change the authentication
 * generation on login/logout/expiry; doing so clears both resolved and
 * in-flight data. `read()` retains expired data so a page can render it as
 * stale while it starts a refresh, but `load()` only reuses fresh entries.
 */
export function createKnowledgeDetailCache({
  now = () => Date.now(),
  ttlMs = KNOWLEDGE_DETAIL_CACHE_TTL_MS,
  maxEntries = KNOWLEDGE_DETAIL_CACHE_MAX_ENTRIES,
  authGeneration = 0,
} = {}) {
  if (!Number.isFinite(ttlMs) || ttlMs < 0) {
    throw new TypeError('ttlMs must be a non-negative finite number')
  }
  if (!Number.isInteger(maxEntries) || maxEntries < 1) {
    throw new TypeError('maxEntries must be a positive integer')
  }
  if (typeof now !== 'function') {
    throw new TypeError('now must be a function')
  }

  let activeGeneration = authGeneration
  let invalidationEpoch = 0
  const entries = new Map()
  const inFlight = new Map()
  const keyRevisions = new Map()

  const currentKey = kbName => knowledgeDetailCacheKey(activeGeneration, kbName)

  const revisionFor = key => keyRevisions.get(key) || 0

  const touch = (key, entry) => {
    entries.delete(key)
    entries.set(key, entry)
    while (entries.size > maxEntries) {
      const oldestKey = entries.keys().next().value
      entries.delete(oldestKey)
    }
  }

  const read = kbName => {
    const key = currentKey(kbName)
    const entry = entries.get(key)
    if (!entry) return null

    touch(key, entry)
    const ageMs = Math.max(0, Number(now()) - entry.cachedAt)
    return {
      value: entry.value,
      cachedAt: entry.cachedAt,
      ageMs,
      fresh: ageMs <= ttlMs,
    }
  }

  const invalidate = kbName => {
    const key = currentKey(kbName)
    entries.delete(key)
    inFlight.delete(key)
    keyRevisions.set(key, revisionFor(key) + 1)
  }

  const invalidateAll = () => {
    invalidationEpoch += 1
    entries.clear()
    inFlight.clear()
    keyRevisions.clear()
  }

  const setAuthGeneration = generation => {
    if (Object.is(activeGeneration, generation)) return false
    activeGeneration = generation
    invalidateAll()
    return true
  }

  const load = (kbName, loader, { force = false } = {}) => {
    const key = currentKey(kbName)
    if (typeof loader !== 'function') {
      throw new TypeError('loader must be a function')
    }

    const snapshot = read(kbName)
    if (!force && snapshot?.fresh) return Promise.resolve(snapshot.value)

    const existing = inFlight.get(key)
    if (existing) return existing.promise

    const requestEpoch = invalidationEpoch
    const requestRevision = revisionFor(key)
    const requestGeneration = activeGeneration
    let request
    request = Promise.resolve()
      .then(() => loader({ kbName, authGeneration: requestGeneration }))
      .then(value => {
        const activeRequest = inFlight.get(key)
        if (
          activeRequest?.promise === request
          && invalidationEpoch === requestEpoch
          && revisionFor(key) === requestRevision
          && Object.is(activeGeneration, requestGeneration)
        ) {
          touch(key, { value, cachedAt: Number(now()) })
        }
        return value
      })
      .finally(() => {
        if (inFlight.get(key)?.promise === request) {
          inFlight.delete(key)
        }
      })

    inFlight.set(key, { promise: request })
    return request
  }

  return {
    read,
    load,
    invalidate,
    invalidateAll,
    setAuthGeneration,
    getAuthGeneration: () => activeGeneration,
    get size() {
      return entries.size
    },
    get inFlightSize() {
      return inFlight.size
    },
  }
}

export const knowledgeDetailCache = createKnowledgeDetailCache()
