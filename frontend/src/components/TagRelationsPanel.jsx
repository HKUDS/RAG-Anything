import { useEffect, useState } from 'react'
import { FileText, Link2, Loader2, Search, Tag } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../utils/api'

export default function TagRelationsPanel({ kbName, selectedTagId, onSelectTag }) {
  const [tags, setTags] = useState([])
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api.listAllKnowledgeTags({ kb: kbName, query, signal: controller.signal })
      .then(data => setTags(Array.isArray(data.tags) ? data.tags : []))
      .catch(() => setTags([]))
    return () => controller.abort()
  }, [kbName, query])

  useEffect(() => {
    if (!selectedTagId) {
      setResult(null)
      return undefined
    }
    const controller = new AbortController()
    setLoading(true)
    api.getKnowledgeTagLinks(selectedTagId, { kb: kbName, signal: controller.signal })
      .then(data => setResult(data))
      .catch(() => setResult(null))
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [kbName, selectedTagId])

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(220px,0.32fr)_minmax(0,1fr)]">
      <aside className="card p-4 space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-ink-body flex items-center gap-2"><Tag size={15} />标签关联</h3>
          <p className="text-xs text-ink-muted mt-1">选择标签，查看跨文档的相关切块。</p>
        </div>
        <label className="relative block">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
          <span className="sr-only">搜索标签</span>
          <input className="input-field w-full pl-8 py-2 text-xs" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索标签" />
        </label>
        <div className="max-h-96 overflow-y-auto space-y-1">
          {tags.map(tag => (
            <button key={tag.id} type="button" onClick={() => onSelectTag(String(tag.id))} className={`w-full text-left rounded-lg px-3 py-2 transition-colors ${String(tag.id) === String(selectedTagId) ? 'bg-sky-50 text-sky-700' : 'text-ink-body hover:bg-cloud-100'}`}>
              <span className="block truncate text-sm font-medium">{tag.name}</span>
              <span className="text-2xs text-ink-muted">{tag.document_count} 篇文档 · {tag.chunk_count} 个切块</span>
            </button>
          ))}
          {tags.length === 0 ? <p className="py-5 text-center text-xs text-ink-muted">暂无匹配标签</p> : null}
        </div>
      </aside>

      <section className="card p-4 min-w-0">
        {!selectedTagId ? <div className="py-16 text-center text-ink-muted"><Link2 size={30} className="mx-auto mb-3 text-cloud-400" /><p className="text-sm">选择一个标签查看关联文档</p></div> : null}
        {selectedTagId && loading ? <div className="py-16 text-center text-ink-muted"><Loader2 size={24} className="mx-auto animate-spin" /></div> : null}
        {selectedTagId && !loading && result ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-ink-body flex items-center gap-2"><Tag size={15} className="text-sky-500" />{result.tag?.name}</h3><p className="text-xs text-ink-muted mt-1">关联 {result.document_count} 篇文档、{result.chunk_count} 个切块</p></div></div>
            {result.documents?.map(group => (
              <article key={group.document.id} className="border border-cloud-200 rounded-lg overflow-hidden">
                <div className="flex items-center gap-2 px-3 py-2 bg-cloud-50 text-sm font-medium text-ink-body"><FileText size={14} className="text-sky-500" />{group.document.file}</div>
                <div className="divide-y divide-cloud-200">
                  {group.chunks.map(chunk => (
                    <Link key={chunk.chunk_id} className="block px-3 py-2.5 hover:bg-sky-50 transition-colors" to={`/knowledge/${encodeURIComponent(kbName)}/documents/${encodeURIComponent(group.document.id)}/chunks/${encodeURIComponent(chunk.chunk_id)}?tag=${encodeURIComponent(selectedTagId)}`}>
                      <span className="text-2xs text-ink-muted">切块 {Number(chunk.chunk_order_index || 0) + 1}{chunk.page_idx != null ? ` · 第 ${chunk.page_idx} 页` : ''}</span>
                      <p className="mt-1 text-xs leading-5 text-ink-body line-clamp-2">{chunk.content}</p>
                    </Link>
                  ))}
                </div>
              </article>
            ))}
            {result.documents?.length === 0 ? <p className="py-12 text-center text-sm text-ink-muted">该标签暂时没有可用的关联切块</p> : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}
