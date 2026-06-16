import { FileText, Scissors, Cpu, Search, Bot, Download } from 'lucide-react'

export const NODE_TYPES = [
  {
    id: 'document_input',
    label: '文档输入',
    icon: 'FileText',
    color: '#3b82f6',
    bgColor: '#eff6ff',
    borderColor: '#93c5fd',
    inputs: 0,
    outputs: 1,
    defaults: { file_type: '.pdf', max_size_mb: 100, file_name: '' },
    configFields: [
      { key: 'label', label: '节点名称', type: 'text', default: '文档输入' },
      { key: 'file_name', label: '选择文件', type: 'file_picker', filterKey: 'file_type' },
      { key: 'file_type', label: '文件类型筛选', type: 'select', options: ['.pdf', '.docx', '.txt', '.md', '.jpg/.png', '全部'], default: '.pdf' },
      { key: 'max_size_mb', label: '最大文件大小 (MB)', type: 'number', default: 100 },
    ],
  },
  {
    id: 'text_splitter',
    label: '文本分割',
    icon: 'Scissors',
    color: '#22c55e',
    bgColor: '#f0fdf4',
    borderColor: '#86efac',
    inputs: 1,
    outputs: 1,
    defaults: { chunk_size: 800, chunk_overlap: 100 },
    configFields: [
      { key: 'label', label: '节点名称', type: 'text', default: '文本分割' },
      { key: 'chunk_size', label: '分块大小 (tokens)', type: 'number', default: 800 },
      { key: 'chunk_overlap', label: '重叠量 (tokens)', type: 'number', default: 100 },
    ],
  },
  {
    id: 'embedding',
    label: '嵌入向量',
    icon: 'Cpu',
    color: '#a855f7',
    bgColor: '#faf5ff',
    borderColor: '#d8b4fe',
    inputs: 1,
    outputs: 1,
    defaults: { model: '', dims: 1024 },
    configFields: [
      { key: 'label', label: '节点名称', type: 'text', default: '嵌入向量' },
      { key: 'model', label: '嵌入模型', type: 'model_select', default: '' },
      { key: 'dims', label: '向量维度', type: 'number', default: 1024 },
    ],
  },
  {
    id: 'retriever',
    label: '检索器',
    icon: 'Search',
    color: '#f59e0b',
    bgColor: '#fffbeb',
    borderColor: '#fcd34d',
    inputs: 1,
    outputs: 1,
    defaults: { top_k: 10, mode: 'hybrid', query_text: '' },
    configFields: [
      { key: 'label', label: '节点名称', type: 'text', default: '检索器' },
      { key: 'query_text', label: '检索问题（可选）', type: 'textarea', default: '' },
      { key: 'top_k', label: 'Top-K', type: 'number', default: 10 },
      { key: 'mode', label: '检索模式（KB降级时使用）', type: 'select', options: ['hybrid', 'vector', 'bm25', 'rrf'], default: 'hybrid' },
    ],
  },
  {
    id: 'llm_answer',
    label: 'LLM 回答',
    icon: 'Bot',
    color: '#f43f5e',
    bgColor: '#fff1f2',
    borderColor: '#fda4af',
    inputs: 1,
    outputs: 1,
    defaults: { model: '', temperature: 0.1, system_prompt: '' },
    configFields: [
      { key: 'label', label: '节点名称', type: 'text', default: 'LLM 回答' },
      { key: 'model', label: '模型', type: 'model_select', default: '' },
      { key: 'temperature', label: '温度', type: 'number', default: 0.1, min: 0, max: 2, step: 0.1 },
      { key: 'system_prompt', label: '系统提示词', type: 'textarea', default: '' },
    ],
  },
  {
    id: 'output',
    label: '输出',
    icon: 'Download',
    color: '#6b7280',
    bgColor: '#f9fafb',
    borderColor: '#d1d5db',
    inputs: 1,
    outputs: 0,
    defaults: { format: 'markdown' },
    configFields: [
      { key: 'label', label: '节点名称', type: 'text', default: '输出' },
      { key: 'format', label: '输出格式', type: 'select', options: ['text', 'markdown', 'json'], default: 'markdown' },
    ],
  },
]

export const ICON_MAP = { FileText, Scissors, Cpu, Search, Bot, Download }

export function getNodeType(id) {
  return NODE_TYPES.find(t => t.id === id)
}

export function createDefaultNode(typeId, position) {
  const def = getNodeType(typeId)
  if (!def) return null
  return {
    id: `${typeId}-${crypto.randomUUID().slice(0, 8)}`,
    type: 'custom',
    position: position || { x: 100, y: 100 },
    data: {
      nodeType: typeId,
      label: def.label,
      ...def.defaults,
    },
  }
}
