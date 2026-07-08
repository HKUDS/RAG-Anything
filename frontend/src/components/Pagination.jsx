import { ChevronLeft, ChevronRight, MoreHorizontal } from 'lucide-react'

export default function Pagination({ page, totalPages, onPageChange, className = '' }) {
  if (totalPages <= 1) return null

  const pages = []
  const maxVisible = 5
  let start = Math.max(1, page - Math.floor(maxVisible / 2))
  let end = Math.min(totalPages, start + maxVisible - 1)

  if (end - start + 1 < maxVisible) {
    start = Math.max(1, end - maxVisible + 1)
  }

  for (let i = start; i <= end; i += 1) {
    pages.push(i)
  }

  const showStart = start > 1
  const showEnd = end < totalPages

  return (
    <nav className={`pagination ${className}`} aria-label="分页">
      <span className="pagination-summary">
        第 {page} / {totalPages} 页
      </span>
      <div className="pagination-controls">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="上一页"
          className="pagination-btn pagination-arrow"
        >
          <ChevronLeft size={14} className="text-ink-body" aria-hidden="true" />
        </button>
        {showStart && (
          <>
            <button
              onClick={() => onPageChange(1)}
              className="pagination-btn"
              aria-label="第 1 页"
            >
              1
            </button>
            {start > 2 && (
              <span className="pagination-ellipsis" aria-hidden="true">
                <MoreHorizontal size={14} />
              </span>
            )}
          </>
        )}
        {pages.map(p => (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            aria-current={p === page ? 'page' : undefined}
            className={`pagination-btn ${p === page ? 'is-active' : ''}`}
          >
            {p}
          </button>
        ))}
        {showEnd && (
          <>
            {end < totalPages - 1 && (
              <span className="pagination-ellipsis" aria-hidden="true">
                <MoreHorizontal size={14} />
              </span>
            )}
            <button
              onClick={() => onPageChange(totalPages)}
              className="pagination-btn"
              aria-label={`第 ${totalPages} 页`}
            >
              {totalPages}
            </button>
          </>
        )}
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="下一页"
          className="pagination-btn pagination-arrow"
        >
          <ChevronRight size={14} className="text-ink-body" aria-hidden="true" />
        </button>
      </div>
    </nav>
  )
}
