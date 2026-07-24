export const PAGE_SIZE_OPTIONS = Object.freeze([10, 20, 50])
export const DEFAULT_PAGE_SIZE = PAGE_SIZE_OPTIONS[0]

export function normalizePageSize(value, options = PAGE_SIZE_OPTIONS, fallback = DEFAULT_PAGE_SIZE) {
  const candidateOptions = Array.isArray(options) && options.length > 0 ? options : PAGE_SIZE_OPTIONS
  const allowed = candidateOptions
    .map(option => Number(option))
    .filter((option, index, values) => Number.isInteger(option) && option > 0 && values.indexOf(option) === index)
  const safeAllowed = allowed.length > 0 ? allowed : [...PAGE_SIZE_OPTIONS]
  const parsed = typeof value === 'string' && value.trim() === '' ? NaN : Number(value)
  const safeFallbackValue = Number(fallback)
  const safeFallback = safeAllowed.includes(safeFallbackValue) ? safeFallbackValue : safeAllowed[0]
  return safeAllowed.includes(parsed) ? parsed : safeFallback
}

export function getStoredPageSize(storageKey, options = PAGE_SIZE_OPTIONS, fallback = DEFAULT_PAGE_SIZE) {
  const defaultValue = normalizePageSize(fallback, options, DEFAULT_PAGE_SIZE)
  if (typeof window === 'undefined' || !storageKey) return defaultValue

  try {
    return normalizePageSize(window.localStorage.getItem(storageKey), options, defaultValue)
  } catch {
    return defaultValue
  }
}

export function storePageSize(storageKey, value, options = PAGE_SIZE_OPTIONS, fallback = DEFAULT_PAGE_SIZE) {
  const normalized = normalizePageSize(value, options, fallback)
  if (typeof window !== 'undefined' && storageKey) {
    try {
      window.localStorage.setItem(storageKey, String(normalized))
    } catch {
      // Storage can be unavailable in private browsing or restricted embeds.
    }
  }
  return normalized
}

export function getTotalPages(totalItems, pageSize) {
  const size = normalizePageSize(pageSize)
  const parsedTotal = Number(totalItems)
  const total = Math.max(0, Number.isFinite(parsedTotal) ? parsedTotal : 0)
  return Math.max(1, Math.ceil(total / size))
}

export function clampPage(page, totalPages) {
  const parsedTotalPages = Number(totalPages)
  const safeTotalPages = Number.isInteger(parsedTotalPages) && parsedTotalPages > 0 ? parsedTotalPages : 1
  const parsed = typeof page === 'string' && page.trim() === '' ? NaN : Number(page)
  return Math.min(safeTotalPages, Math.max(1, Number.isInteger(parsed) ? parsed : 1))
}
