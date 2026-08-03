// 全局统计（当前 KB）缓存的纯实现：按 key 存取、TTL 过期、in-flight 去重、显式失效。
// 不依赖网络/DOM，便于单元测试。默认 TTL 30s。

export const GLOBAL_STATS_CACHE_TTL_MS = 30_000

export function createGlobalStatsCache({ ttlMs = GLOBAL_STATS_CACHE_TTL_MS, now = Date.now } = {}) {
  if (!Number.isFinite(ttlMs) || ttlMs < 0) {
    throw new TypeError('ttlMs 必须是非负有限数字')
  }
  let generation = 0
  const entries = new Map()
  const inflight = new Map()

  function isFresh(at) {
    return (now() - at) < ttlMs
  }

  function get(key) {
    const entry = entries.get(key)
    if (!entry) return undefined
    if (!isFresh(entry.at)) {
      entries.delete(key)
      return undefined
    }
    return entry.value
  }

  function set(key, value) {
    entries.set(key, { value, at: now() })
  }

  function getOrLoad(key, loader) {
    const cached = get(key)
    if (cached !== undefined) return Promise.resolve(cached)

    const existing = inflight.get(key)
    if (existing) return existing

    const requestGeneration = generation
    let request
    request = Promise.resolve()
      .then(() => loader())
      .then(value => {
        // 仅在同一代内提交，避免失效后仍在途的旧请求写入缓存
        if (requestGeneration === generation) {
          entries.set(key, { value, at: now() })
        }
        return value
      })
      .finally(() => {
        if (inflight.get(key) === request) inflight.delete(key)
      })
    inflight.set(key, request)
    return request
  }

  // 不带 key 时清空全部并让所有在途请求失效；带 key 时仅失效该 key。
  function invalidate(key) {
    generation += 1
    if (key === undefined) {
      entries.clear()
      inflight.clear()
      return
    }
    entries.delete(key)
    inflight.delete(key)
  }

  return { get, set, getOrLoad, invalidate }
}