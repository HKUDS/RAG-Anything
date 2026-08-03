/** Format an ISO timestamp as zh-CN date and time in the viewer's local timezone. */
export function formatDate(iso) {
  if (!iso || typeof iso !== 'string') return ''
  // ???? ISO ????????? "0"??? Date ????????????? 2000-01-01??
  if (!/[-T]/.test(iso)) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
