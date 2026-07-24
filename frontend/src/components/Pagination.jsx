import { ChevronLeft, ChevronRight, MoreHorizontal } from 'lucide-react'
import { DEFAULT_PAGE_SIZE, normalizePageSize, PAGE_SIZE_OPTIONS } from '../utils/pagination'

export default function Pagination({
  page,
  totalPages,
  onPageChange,
  pageSize = DEFAULT_PAGE_SIZE,
  onPageSizeChange,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
  className = '',
}) {
  const safeTotalPages = Math.max(1, Number(totalPages) || 1)
  const currentPage = Math.min(safeTotalPages, Math.max(1, Number(page) || 1))
  const hasPageSizeControl = typeof onPageSizeChange === 'function'
  const options = (Array.isArray(pageSizeOptions) ? pageSizeOptions : PAGE_SIZE_OPTIONS)
    .map(value => Number(value))
    .filter((value, index, values) => Number.isInteger(value) && value > 0 && values.indexOf(value) === index)
  const safeOptions = options.length > 0 ? options : PAGE_SIZE_OPTIONS
  const selectedPageSize = normalizePageSize(pageSize, safeOptions)

  if (safeTotalPages <= 1 && !hasPageSizeControl) return null

  const pages = []
  const maxVisible = 5
  let start = Math.max(1, currentPage - Math.floor(maxVisible / 2))
  let end = Math.min(safeTotalPages, start + maxVisible - 1)

  if (end - start + 1 < maxVisible) {
    start = Math.max(1, end - maxVisible + 1)
  }

  for (let value = start; value <= end; value += 1) {
    pages.push(value)
  }

  const showStart = start > 1
  const showEnd = end < safeTotalPages

  return (
    <nav className={`pagination ${className}`} aria-label="分页">
      <div className="pagination-meta">
        {hasPageSizeControl ? (
          <label className="pagination-page-size">
            <span>每页</span>
            <select
              value={selectedPageSize}
              aria-label="每页显示数量"
              onChange={event => onPageSizeChange(Number(event.target.value))}
            >
              {safeOptions.map(value => <option key={value} value={value}>{value}</option>)}
            </select>
            <span>条</span>
          </label>
        ) : null}

        <span className="pagination-summary">
          第 {currentPage} / {safeTotalPages} 页
        </span>
      </div>

      {safeTotalPages > 1 ? (
        <div className="pagination-controls">
          <button
            type="button"
            onClick={() => onPageChange(currentPage - 1)}
            disabled={currentPage <= 1}
            aria-label="上一页"
            className="pagination-btn pagination-arrow"
          >
            <ChevronLeft size={14} aria-hidden="true" />
          </button>
          {showStart && (
            <>
              <button type="button" onClick={() => onPageChange(1)} className="pagination-btn" aria-label="第 1 页">1</button>
              {start > 2 ? <span className="pagination-ellipsis" aria-hidden="true"><MoreHorizontal size={14} /></span> : null}
            </>
          )}
          {pages.map(value => (
            <button
              type="button"
              key={value}
              onClick={() => onPageChange(value)}
              aria-current={value === currentPage ? 'page' : undefined}
              className={`pagination-btn ${value === currentPage ? 'is-active' : ''}`}
            >
              {value}
            </button>
          ))}
          {showEnd && (
            <>
              {end < safeTotalPages - 1 ? <span className="pagination-ellipsis" aria-hidden="true"><MoreHorizontal size={14} /></span> : null}
              <button type="button" onClick={() => onPageChange(safeTotalPages)} className="pagination-btn" aria-label={`第 ${safeTotalPages} 页`}>{safeTotalPages}</button>
            </>
          )}
          <button
            type="button"
            onClick={() => onPageChange(currentPage + 1)}
            disabled={currentPage >= safeTotalPages}
            aria-label="下一页"
            className="pagination-btn pagination-arrow"
          >
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        </div>
      ) : <span className="pagination-controls-placeholder" aria-hidden="true" />}
    </nav>
  )
}
