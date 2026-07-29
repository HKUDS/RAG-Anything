const MEDIA_ID_PATTERN = /^[A-Za-z0-9_-]{16,128}$/
const LEGACY_GRANT_PATTERN = /^[A-Za-z0-9_-]{20,128}\.[a-f0-9]{64}$/

export function controlledMediaUrl(media) {
  if (!media || typeof media !== 'object') return ''
  const mediaId = media.media_id
  const kb = media.kb || media.media_kb
  const legacyGrant = media.legacy_grant
  if (typeof legacyGrant === 'string' && LEGACY_GRANT_PATTERN.test(legacyGrant)) {
    if (typeof kb !== 'string' || !kb) return ''
    return `/api/knowledge/media/legacy/${encodeURIComponent(legacyGrant)}?kb=${encodeURIComponent(kb)}`
  }
  if (typeof mediaId !== 'string' || !MEDIA_ID_PATTERN.test(mediaId)) return ''
  if (typeof kb !== 'string' || !kb) return ''
  return `/api/knowledge/media/${encodeURIComponent(mediaId)}?kb=${encodeURIComponent(kb)}`
}

export function publicMediaUrl(media) {
  if (!media || typeof media !== 'object' || media.media_id) return ''
  const value = typeof media.media_url === 'string' ? media.media_url : ''
  return /^https:\/\//i.test(value) ? value : ''
}
