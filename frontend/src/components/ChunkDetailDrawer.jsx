import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X, Search, ChevronRight, Loader2, FileText, Scissors, Zap,
  ImageIcon, Table, Sigma, Video
} from 'lucide-react'
import { getToken } from '../utils/api'

const TYPE_ICONS = { image: ImageIcon, table: Table, equation: Sigma, video: Video }
const TYPE_LABELS = { image: '图片', table: '表格', equation: '公式', video: '视频' }
const TYPE_COLORS = {
  image: 'text-sage-500',
  table: 'text-amber-500',
  equation: 'text-sky-500',
  video: 'text-ink-muted',
}

/**
 * Clean up multimodal chunk content for display.
 *
 * VLM-processed chunks store their description using English template headers
 * (e.g. "Image Content Analysis:", "Visual Analysis:").  This function strips
 * the boilerplate and returns only the meaningful content, preferring the
 * Chinese/RAG-useful parts (neighbor text, visual analysis, captions).
 *
 * Falls back to the raw content if no template patterns are detected.
 */
function cleanMultimodalContent(rawContent) {
  if (!rawContent) return rawContent

  // 检测模板类型
  const isImage = rawContent.includes('Image Content Analysis')
  const isTable = rawContent.includes('Table Analysis')
  const isEquation = rawContent.includes('Mathematical Equation Analysis')
  const isVideo = rawContent.includes('Video Content Analysis')
  const isGeneric = rawContent.includes('Content Analysis') && !isImage && !isTable && !isEquation && !isVideo

  if (!isImage && !isTable && !isEquation && !isVideo && !isGeneric) {
    return rawContent // plain text chunk, return as-is
  }

  // 从模板中提取有效字段
  const parts = []

  const extract = (label) => {
    // 匹配“标签: 值”或“- 标签: 值”格式
    const regex = new RegExp(`(?:-\\s*)?${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}:\\s*(.+?)(?:\\n|$)`, 'i')
    const match = rawContent.match(regex)
    if (match && match[1].trim() && match[1].trim().toLowerCase() !== 'none') {
      return match[1].trim()
    }
    return null
  }

  if (isImage || isVideo) {
    const neighbor = extract('Neighbor Text')
    const analysis = extract('(?:Visual|Video)\\s*Analysis')
    const captions = extract('Captions')
    const footnotes = extract('Footnotes')
    if (captions) parts.push(captions)
    if (neighbor) parts.push(neighbor)
    if (analysis) parts.push(analysis)
    if (footnotes) parts.push(footnotes)
  } else if (isTable) {
    const caption = extract('Caption')
    const analysis = extract('Analysis')
    if (caption) parts.push(caption)
    if (analysis) parts.push(analysis)
  } else if (isEquation) {
    const equation = extract('Equation')
    const analysis = extract('Mathematical Analysis')
    if (equation) parts.push(equation)
    if (analysis) parts.push(analysis)
  } else if (isGeneric) {
    const content = extract('Content')
    const analysis = extract('Analysis')
    if (content) parts.push(content)
    if (analysis) parts.push(analysis)
  }

  // 如果未能提取有效信息，则回退到最后一行（通常是 VLM 描述）
  if (parts.length === 0) {
    const lines = rawContent.split('\n').filter(l => l.trim())
    const lastLine = lines[lines.length - 1]
    if (lastLine && lastLine.length > 20) {
      parts.push(lastLine.replace(/^(?:Visual|Video|Mathematical)?\s*Analysis:\s*/i, '').trim())
    }
  }

  return parts.length > 0 ? parts.join('\n\n') : rawContent
}

export default function ChunkDetailDrawer({
  doc,
  chunksData,
  chunksLoading,
  expandedChunks,
  chunkFilterText,
  filteredChunks,
  onClose,
  onToggleChunk,
  onExpandAll,
  onCollapseAll,
  onFilterChange,
}) {
  const authToken = useMemo(() => getToken(), [])

  // 全局 Escape 键监听
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const totalTokens = useMemo(
    () => chunksData.reduce((s, c) => s + (c.tokens || 0), 0),
    [chunksData]
  )

  return (
    <motion.div
      className="fixed inset-0 z-50 flex justify-end"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose} role="dialog" aria-modal="true" aria-label="分块详情"
    >
      <div className="absolute inset-0 bg-sky-900/20" />
      <motion.div
        className="relative w-[520px] max-w-[90vw] card m-3 flex flex-col overflow-hidden"
        initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        onClick={e => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-cloud-200 shrink-0">
          <div className="min-w-0">
            <h3 className="font-semibold text-ink-primary truncate" title={doc.file}>
              分块详情：{doc.file}
            </h3>
          </div>
          <button className="btn-ghost p-1 shrink-0 ml-2" onClick={onClose} aria-label="关闭分块详情">
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        {/* 统计栏与控制区 */}
        <div className="px-6 py-3 border-b border-cloud-100 shrink-0 space-y-2">
          <div className="flex items-center gap-4 text-xs text-ink-muted flex-wrap">
            <span className="flex items-center gap-1">
              <Scissors size={12} />
              {chunksLoading ? '加载中…' : `${chunksData.length} 块`}
            </span>
            <span className="flex items-center gap-1">
              <Zap size={12} />
              {chunksLoading ? '-' : `${totalTokens.toLocaleString()} tokens`}
            </span>
            {chunkFilterText.trim() && (
              <span className="text-sky-600">
                显示 {filteredChunks.length} / {chunksData.length} 块
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn-ghost text-xs py-1 px-2"
              onClick={onExpandAll}
              disabled={chunksLoading || chunksData.length === 0}
            >
              全部展开
            </button>
            <button
              className="btn-ghost text-xs py-1 px-2"
              onClick={onCollapseAll}
              disabled={chunksLoading || chunksData.length === 0}
            >
              全部折叠
            </button>
          </div>
        </div>

        {/* 筛选输入 */}
        <div className="px-6 py-2 shrink-0">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none" />
            <input
              className="input-field text-sm w-full pl-9 pr-3"
              placeholder="搜索切块内容…"
              value={chunkFilterText}
              onChange={e => onFilterChange(e.target.value)}
            />
          </div>
        </div>

        {/* 分块列表 */}
        <div className="flex-1 overflow-y-auto px-6 py-3 space-y-2">
          {chunksLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-sky-500" />
              <span className="ml-2 text-sm text-ink-muted">加载分块数据…</span>
            </div>
          ) : filteredChunks.length === 0 ? (
            <div className="py-12 text-center">
              <FileText size={36} className="mx-auto mb-3 text-cloud-400" />
              <p className="text-sm text-ink-muted">
                {chunkFilterText.trim() ? '没有匹配的切块' : '暂无切块数据'}
              </p>
            </div>
          ) : (
            filteredChunks.map((chunk, idx) => {
              const isExpanded = expandedChunks[idx] || false
              // 为缺少标记的旧文档从内容中识别多模态类型
              const detectedType = chunk.original_type || (
                chunk.content?.includes('Image Content Analysis') ? 'image' :
                chunk.content?.includes('Table Analysis') ? 'table' :
                chunk.content?.includes('Mathematical Equation Analysis') ? 'equation' :
                chunk.content?.includes('Video Content Analysis') ? 'video' :
                null
              )
              const isMultimodal = chunk.is_multimodal || !!detectedType
              const TypeIcon = detectedType ? TYPE_ICONS[detectedType] : null

              // 同步清理预览内容
              const displayContent = isMultimodal ? cleanMultimodalContent(chunk.content) : (chunk.content || '')
              const preview = displayContent.replace(/\n/g, ' ').slice(0, 120)
              const hasMore = displayContent.length > 120

              const imageUrl = chunk.media_url
                || (chunk.media_path
                  ? `/api/files/image?path=${encodeURIComponent(chunk.media_path)}&token=${encodeURIComponent(authToken)}`
                  : null)

              return (
                <div
                  key={chunk.chunk_id || idx}
                  className="border border-cloud-200 rounded-lg overflow-hidden transition-shadow hover:shadow-cloud-sm"
                >
                  {/* 折叠态头部 */}
                  <button
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-cloud-50 transition-colors"
                    onClick={() => onToggleChunk(idx)}
                  >
                    <ChevronRight
                      size={14}
                      className={`text-ink-muted shrink-0 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                    />
                    <span className="font-mono text-xs text-ink-muted shrink-0">
                      #{chunk.chunk_order_index != null ? chunk.chunk_order_index + 1 : idx + 1}
                    </span>
                    <span className="text-xs text-ink-muted shrink-0">
                      {chunk.tokens?.toLocaleString() || 0} tokens
                    </span>
                    {chunk.page_idx != null && (
                      <span className="text-xs text-ink-muted shrink-0">· 第{chunk.page_idx}页</span>
                    )}
                    {TypeIcon && (
                      <span className="flex items-center gap-1 text-xs shrink-0" title={detectedType}>
                        <TypeIcon size={14} className={TYPE_COLORS[detectedType] || 'text-ink-muted'} />
                        <span className="text-ink-muted">
                          {TYPE_LABELS[detectedType] || ''}
                        </span>
                      </span>
                    )}
                    <span className="flex-1 text-xs text-ink-muted truncate ml-auto text-right">
                      {preview}{hasMore ? '…' : ''}
                    </span>
                  </button>
                  {/* 展开内容 */}
                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="px-4 pb-4 border-t border-cloud-100">
                          {/* 多模态信息 */}
                          {isMultimodal && (
                            <div className="mt-3 flex flex-wrap items-start gap-3">
                              {imageUrl && (
                                <img
                                  src={imageUrl}
                                  alt={chunk.modal_entity_name || '切块图片'}
                                  className="rounded border border-cloud-200 shrink-0"
                                  style={{ width: '120px', height: '80px', objectFit: 'cover' }}
                                  onError={(e) => { e.target.style.display = 'none' }}
                                />
                              )}
                              <div className="text-xs text-ink-muted space-y-1 min-w-0">
                                {chunk.modal_entity_name && (
                                  <p><span className="font-medium">名称：</span>{chunk.modal_entity_name}</p>
                                )}
                                {chunk.page_idx != null && (
                                  <p><span className="font-medium">位置：</span>第 {chunk.page_idx} 页</p>
                                )}
                                {chunk.media_path && (
                                  <p className="truncate"><span className="font-medium">路径：</span>{chunk.media_path.split(/[/\\]/).pop()}</p>
                                )}
                              </div>
                            </div>
                          )}
                          {/* 完整内容，已针对多模态分块清理 */}
                          <div className="mt-3 p-3 bg-cloud-50 rounded-lg font-mono text-xs text-ink-body whitespace-pre-wrap max-h-60 overflow-y-auto">
                            {cleanMultimodalContent(chunk.content) || '(空内容)'}
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )
            })
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
