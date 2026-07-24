import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import {
  Plus, Bot, Trash2, Edit3, X, MessageSquare, Database,
  Clock, Cpu, Search, Brain, Layers,
} from 'lucide-react'
import { api } from '../utils/api'
import { motion, AnimatePresence } from 'framer-motion'
import Pagination from '../components/Pagination'
import ResourceSortControl from '../components/ResourceSortControl'
import { useAuth } from '../context/AuthContext'
import { sortAgents } from '../utils/agentSorting'
import { clampPage, getStoredPageSize, getTotalPages, storePageSize } from '../utils/pagination'

const MODE_LABELS = { rrf: '融合', hybrid: '混合', local: '精确', global: '全局', naive: '快速' }
const AGENT_MODE_LABELS = { none: '普通', react: 'ReAct', cot: 'CoT' }
const AGENT_MODE_ICONS = { none: MessageSquare, react: Brain, cot: Layers }
const AGENT_GRID_ROWS = 2
const PAGE_SIZE_STORAGE_KEY = 'raganything:pagination:agents'
const AGENT_SORT_OPTIONS = [
  { value: 'updated', label: '更新时间', Icon: Clock, type: 'time' },
  { value: 'lastConversation', label: '最近对话', Icon: MessageSquare, type: 'time' },
  { value: 'conversationCount', label: '对话数量', Icon: Layers, type: 'number' },
]

const ANSWER_STYLE_PRESETS = [
  {
    id: 'rigorous',
    label: '严谨引用型',
    description: '适合制度、课程资料和正式问答',
    prompt: '你是严谨的知识库助手。回答必须基于检索内容；证据不足时直接说明知识库暂无足够信息，不要猜测。先给结论，再给关键依据。',
  },
  {
    id: 'teaching',
    label: '教学讲解型',
    description: '适合学生问答、概念解释和课后辅导',
    prompt: '你是耐心的教学助手。请用学生容易理解的语言回答，先解释核心概念，再用例子或类比帮助理解。复杂问题要拆成几个小步骤，并在最后给出简短总结。',
  },
  {
    id: 'concise',
    label: '简洁答复型',
    description: '适合高频操作咨询和快速查询',
    prompt: '你是高效的知识库助手。请直接回答问题，优先使用短句和要点。只保留用户完成任务需要的关键信息，避免冗长背景。',
  },
  {
    id: 'steps',
    label: '步骤清单型',
    description: '适合流程指引、实验任务和操作手册',
    prompt: '你是擅长拆解流程的助手。回答时请按照前提条件、操作步骤、注意事项、检查结果组织内容。步骤要可执行，每步尽量只包含一个动作。',
  },
]

const normalizePrompt = (value = '') => value.trim().replace(/\r\n/g, '\n')

const AGENT_NUMERIC_LIMITS = {
  max_response_tokens: { min: 512, max: 16384, defaultValue: 4096 },
  retrieval_top_k: { min: 5, max: 200, defaultValue: 40 },
  chunk_top_k: { min: 1, max: 100, defaultValue: 20 },
}

const clampAgentNumber = (field, value) => {
  const limits = AGENT_NUMERIC_LIMITS[field]
  const parsed = Number.parseInt(value, 10)
  if (!Number.isFinite(parsed)) return limits.defaultValue
  return Math.min(limits.max, Math.max(limits.min, parsed))
}

const normalizeAgentPayload = (formData) => ({
  ...formData,
  temperature: Number.parseFloat(formData.temperature) || 0,
  max_response_tokens: clampAgentNumber('max_response_tokens', formData.max_response_tokens),
  retrieval_top_k: clampAgentNumber('retrieval_top_k', formData.retrieval_top_k),
  chunk_top_k: clampAgentNumber('chunk_top_k', formData.chunk_top_k),
  enable_rerank: Boolean(formData.enable_rerank),
  include_references: Boolean(formData.include_references),
})

const upsertAgent = (agents, nextAgent) => [
  nextAgent,
  ...agents.filter(agent => agent.id !== nextAgent.id),
]

export default function AgentsPage({ onToast }) {
  const navigate = useNavigate()
  const { hasPermission } = useAuth()
  const [agents, setAgents] = useState([])
  const [templates, setTemplates] = useState([])
  const [kbs, setKBs] = useState([])
  const [showModal, setShowModal] = useState(false)
  const [editingAgent, setEditingAgent] = useState(null)
  const [form, setForm] = useState(getDefaultForm())
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState('updated')
  const [sortDirection, setSortDirection] = useState('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(() => getStoredPageSize(PAGE_SIZE_STORAGE_KEY))
  const [gridColumns, setGridColumns] = useState(4)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const gridRef = useRef(null)
  const canWrite = hasPermission('agent:write')
  const canDelete = hasPermission('agent:delete')

  const loadData = useCallback(async () => {
    const [agentsResponse, templatesResponse, kbResponse] = await Promise.all([
      api.listAgents(),
      api.getAgentTemplates(),
      api.listKBs(),
    ])
    setAgents(agentsResponse.agents || [])
    setTemplates(templatesResponse.templates || [])
    setKBs(kbResponse.knowledge_bases || [])
    return [agentsResponse, templatesResponse, kbResponse]
  }, [])

  useEffect(() => {
    loadData().catch(err => {
      console.error(err)
      onToast?.(err.message || '加载智能体数据失败', 'error')
    })
  }, [loadData, onToast])
  useEffect(() => { setPage(1) }, [search])
  useLayoutEffect(() => {
    const grid = gridRef.current
    if (!grid) return undefined

    let frame = 0
    const updateGridColumns = () => {
      if (frame) cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const templateColumns = window.getComputedStyle(grid).gridTemplateColumns
        const columns = templateColumns && templateColumns !== 'none'
          ? templateColumns.split(' ').filter(Boolean).length
          : 1

        setGridColumns(Math.max(1, columns))
      })
    }

    updateGridColumns()

    const resizeObserver = typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(updateGridColumns)
      : null

    resizeObserver?.observe(grid)
    window.addEventListener('resize', updateGridColumns)

    return () => {
      if (frame) cancelAnimationFrame(frame)
      resizeObserver?.disconnect()
      window.removeEventListener('resize', updateGridColumns)
    }
  }, [])
  useEffect(() => {
    if (!showModal) return

    const root = document.documentElement
    const body = document.body
    const previousRootOverflow = root.style.overflow
    const previousBodyOverflow = body.style.overflow

    root.classList.add('agent-config-scroll-locked')
    body.classList.add('agent-config-scroll-locked')
    root.style.overflow = 'hidden'
    body.style.overflow = 'hidden'

    return () => {
      root.classList.remove('agent-config-scroll-locked')
      body.classList.remove('agent-config-scroll-locked')
      root.style.overflow = previousRootOverflow
      body.style.overflow = previousBodyOverflow
    }
  }, [showModal])

  function getDefaultForm() {
    return {
      name: '', icon: '', description: '', kb_name: 'default', llm_model: 'qwen-plus',
      temperature: 0.0, max_response_tokens: 4096, query_mode: 'hybrid', agent_mode: 'none',
      retrieval_top_k: 40, chunk_top_k: 20, enable_rerank: false, include_references: true,
      system_prompt: '', use_default_prompt: true, welcome_message: '', template_id: '',
    }
  }

  const resetModalState = () => {
    setEditingAgent(null)
    setForm(getDefaultForm())
    setFormError('')
    setNameTouched(false)
  }

  const closeModal = () => {
    if (saving) return
    setShowModal(false)
    resetModalState()
  }

  const openCreate = () => {
    if (!canWrite) {
      onToast?.('当前账号只能查看智能体，不能创建或编辑。', 'info')
      return
    }
    resetModalState()
    setShowModal(true)
  }

  const openEdit = (agent) => {
    if (!canWrite) {
      onToast?.('当前账号只能查看智能体，不能创建或编辑。', 'info')
      return
    }
    setEditingAgent(agent.id)
    setFormError('')
    setNameTouched(false)
    setForm({
      name: agent.name, icon: agent.icon || '', description: agent.description || '',
      kb_name: agent.kb_name, llm_model: agent.llm_model, temperature: agent.temperature || 0,
      max_response_tokens: clampAgentNumber('max_response_tokens', agent.max_response_tokens),
      query_mode: agent.query_mode, agent_mode: agent.agent_mode || 'none',
      retrieval_top_k: clampAgentNumber('retrieval_top_k', agent.retrieval_top_k),
      chunk_top_k: clampAgentNumber('chunk_top_k', agent.chunk_top_k),
      enable_rerank: Boolean(agent.enable_rerank), include_references: agent.include_references !== false,
      system_prompt: agent.system_prompt || '', use_default_prompt: agent.use_default_prompt !== false,
      welcome_message: agent.welcome_message || '', template_id: agent.template_id || '',
    })
    setShowModal(true)
  }

  const applyTemplate = (tpl) => {
    setForm({
      ...form,
      name: tpl.name.replace(/^[^一-龥]*\s*/, ''),
      icon: tpl.icon || '',
      description: tpl.description || '',
      llm_model: tpl.llm_model || 'qwen-plus',
      temperature: tpl.temperature ?? 0,
      max_response_tokens: clampAgentNumber('max_response_tokens', tpl.max_response_tokens),
      query_mode: tpl.query_mode || 'hybrid',
      agent_mode: tpl.agent_mode || 'none',
      retrieval_top_k: clampAgentNumber('retrieval_top_k', tpl.retrieval_top_k),
      chunk_top_k: clampAgentNumber('chunk_top_k', tpl.chunk_top_k),
      enable_rerank: Boolean(tpl.enable_rerank),
      include_references: tpl.include_references !== false,
      system_prompt: tpl.system_prompt || '',
      use_default_prompt: tpl.use_default_prompt !== false,
      welcome_message: tpl.welcome_message || '',
      template_id: tpl.id,
    })
  }

  const applyAnswerStyle = (preset) => {
    setForm(current => ({
      ...current,
      system_prompt: preset.prompt,
    }))
  }

  const clearAnswerStyle = () => {
    setForm(current => ({
      ...current,
      system_prompt: '',
    }))
  }

  const saveAgent = async () => {
    if (!canWrite) {
      const message = '当前账号只能查看智能体，不能保存修改。'
      setFormError(message)
      onToast?.(message, 'error')
      return
    }
    setNameTouched(true)
    if (!form.name.trim()) {
      const message = '请输入智能体名称'
      setFormError(message)
      onToast?.(message, 'error')
      return
    }

    const payload = normalizeAgentPayload(form)
    setSaving(true)
    setFormError('')
    try {
      const response = editingAgent
        ? await api.updateAgent(editingAgent, payload)
        : await api.createAgent(payload)

      if (response?.agent) {
        setAgents(prev => upsertAgent(prev, response.agent))
      }

      await loadData()
      setShowModal(false)
      resetModalState()
      onToast?.(editingAgent ? '智能体已保存' : '智能体已创建', 'success')
    } catch (e) {
      const message = e.message || '保存智能体失败'
      console.error('保存智能体失败:', e)
      setFormError(message)
      onToast?.(message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const deleteAgent = async (id) => {
    if (!canDelete) {
      onToast?.('当前账号没有删除智能体的权限。', 'error')
      return
    }
    try {
      await api.deleteAgent(id)
      setAgents(prev => prev.filter(agent => agent.id !== id))
      setDeleteConfirm(null)
      await loadData()
      onToast?.('智能体已删除', 'success')
    } catch (e) {
      const message = e.message || '删除智能体失败'
      onToast?.(message, 'error')
    }
  }

  const startChat = (agent) => {
    navigate(`/agents/${agent.id}`)
  }

  const normalizedSearch = search.trim().toLowerCase()
  const filteredAgents = useMemo(() => agents.filter(agent => {
    if (!normalizedSearch) return true
    return [
      agent.name,
      agent.description,
      agent.id,
      agent.kb_name,
      agent.llm_model,
      MODE_LABELS[agent.query_mode],
      AGENT_MODE_LABELS[agent.agent_mode],
    ].some(value => String(value || '').toLowerCase().includes(normalizedSearch))
  }), [agents, normalizedSearch])
  const sortedAgents = useMemo(
    () => sortAgents(filteredAgents, sortField, sortDirection),
    [filteredAgents, sortField, sortDirection]
  )

  const totalPages = getTotalPages(sortedAgents.length, pageSize)
  const currentPage = clampPage(page, totalPages)
  const paginatedAgents = sortedAgents.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const agentGridRows = paginatedAgents.length > 0
    ? Math.max(AGENT_GRID_ROWS, Math.ceil(paginatedAgents.length / Math.max(1, gridColumns)))
    : AGENT_GRID_ROWS
  const agentGridClassName = paginatedAgents.length > 0
    ? 'resource-grid resource-grid-agents resource-grid-agents-fixed-rows'
    : 'resource-grid resource-grid-agents'
  const agentGridStyle = paginatedAgents.length > 0
    ? { '--agent-grid-rows': agentGridRows, '--agent-grid-row-gaps': agentGridRows - 1 }
    : undefined

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const updatePageSize = value => {
    const next = storePageSize(PAGE_SIZE_STORAGE_KEY, value)
    setPageSize(next)
    setPage(1)
  }


  const activeAnswerStyle = ANSWER_STYLE_PRESETS.find(
    preset => normalizePrompt(preset.prompt) === normalizePrompt(form.system_prompt)
  )
  const nameError = nameTouched && !form.name.trim() ? '请输入智能体名称' : ''
  return (
    <div className="resource-page resource-page-agents">
      {/* 头部 */}
      <div className="page-header page-header-divider resource-page-header">
        <div>
          <h2 className="page-title">智能体</h2>
          <p className="page-subtitle">每个智能体拥有独立的知识库、模型和对话配置</p>
        </div>
        <button
          onClick={openCreate}
          className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={!canWrite}
        >
          <Plus size={16} /> 新建智能体
        </button>
      </div>

      <section className="resource-panel">
        {!canWrite && (
          <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            当前账号可查看智能体，但没有编辑权限。创建、编辑和删除操作已禁用。
          </div>
        )}
        <div className="resource-toolbar">
          <div className="relative w-full lg:max-w-md">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none" />
            <input
              className="input-field w-full pl-10 pr-4 text-sm"
              placeholder="搜索智能体名称、描述、知识库或模型"
              aria-label="搜索智能体名称、描述、知识库或模型"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="resource-toolbar-actions">
            <ResourceSortControl
              sortOptions={AGENT_SORT_OPTIONS}
              sortField={sortField}
              sortDirection={sortDirection}
              onSortFieldChange={field => {
                setSortField(field)
                setPage(1)
              }}
              onSortDirectionChange={direction => {
                setSortDirection(direction)
                setPage(1)
              }}
              menuId="agent-sort-options"
              ariaLabel="智能体排序"
            />
            <div className="resource-count">
              共 {agents.length} 个智能体
              {normalizedSearch ? `，匹配到 ${filteredAgents.length} 个结果` : ''}
            </div>
          </div>
        </div>

        {/* 智能体卡片 */}
        <div ref={gridRef} className={agentGridClassName} style={agentGridStyle}>
          {paginatedAgents.map(agent => (
            <div
              key={agent.id}
              className="directory-card resource-card resource-card-agent group cursor-pointer"
              onClick={() => startChat(agent)}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="directory-icon resource-card-agent-icon">
                    {agent.icon ? <span className="text-xl leading-none">{agent.icon}</span> : <Bot size={18} />}
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-ink-primary text-base truncate">{agent.name}</h3>
                    <p className="text-2xs text-ink-muted font-mono truncate">ID: {agent.id}</p>
                  </div>
                </div>
                <div className="resource-card-agent-actions flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                  <button
                    className={`p-1.5 rounded-lg transition-colors ${canWrite ? 'text-ink-muted hover:text-sky-500 hover:bg-sky-50' : 'text-ink-muted/50 cursor-not-allowed'}`}
                    onClick={() => openEdit(agent)}
                    aria-label={`编辑 ${agent.name}`}
                    disabled={!canWrite}
                  >
                    <Edit3 size={14} aria-hidden="true" />
                  </button>
                  <button
                    className={`p-1.5 rounded-lg transition-colors ${canDelete ? 'text-ink-muted hover:text-rose-500 hover:bg-rose-50' : 'text-ink-muted/50 cursor-not-allowed'}`}
                    onClick={() => setDeleteConfirm(agent.id)}
                    aria-label={`删除 ${agent.name}`}
                    disabled={!canDelete}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              </div>

              {agent.description ? (
                <p className="resource-card-agent-desc text-xs text-ink-muted leading-relaxed min-h-[36px] line-clamp-2">{agent.description}</p>
              ) : (
                <p className="text-xs text-ink-muted/60 leading-relaxed min-h-[36px] line-clamp-2">暂无描述</p>
              )}

              <div className="resource-card-agent-tags flex flex-wrap gap-1.5">
                <span className="tag tag-purple">
                  <Database size={10} /> {agent.kb_name}
                </span>
                <span className="tag tag-blue">
                  <Cpu size={10} /> {agent.llm_model}
                </span>
                <span className="tag tag-amber">
                  <Search size={10} /> {MODE_LABELS[agent.query_mode] || agent.query_mode}
                </span>
                <span className="tag tag-teal">
                  {React.createElement(AGENT_MODE_ICONS[agent.agent_mode] || MessageSquare, { size: 10 })} {AGENT_MODE_LABELS[agent.agent_mode] || '普通'}
                </span>
              </div>

              <button className="directory-footer resource-card-agent-footer w-full flex items-center justify-center gap-2 text-xs font-medium text-ink-primary hover:text-sky-600 transition-colors">
                <MessageSquare size={13} /> 开始对话
              </button>
            </div>
          ))}
        </div>

        {sortedAgents.length > 0 && (
          <Pagination
            page={currentPage}
            totalPages={totalPages}
            onPageChange={setPage}
            pageSize={pageSize}
            onPageSizeChange={updatePageSize}
            className="resource-pagination resource-pagination-agents"
          />
        )}

        {agents.length === 0 && (
          <div className="empty-state resource-empty-state">
            <div className="empty-state-icon"><Bot size={48} className="text-cloud-400" /></div>
            <p className="empty-state-title">这里还没有智能体</p>
            <p className="empty-state-desc">创建智能体以开始使用知识库问答和检索功能</p>
            <button
              onClick={openCreate}
              className="btn-primary mt-6 disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!canWrite}
            >
              创建第一个智能体
            </button>
          </div>
        )}

        {agents.length > 0 && filteredAgents.length === 0 && (
          <div className="empty-state resource-empty-state">
            <div className="empty-state-icon"><Search size={40} className="text-cloud-400" /></div>
            <p className="empty-state-title">没有找到匹配的智能体</p>
            <p className="empty-state-desc">试试更短的关键词，或者搜索名称、知识库与模型字段</p>
          </div>
        )}
      </section>

      {/* 创建/编辑弹窗 */}
      {createPortal(
      <AnimatePresence>
        {showModal && (
          <div className="agent-config-overlay" onClick={closeModal} role="dialog" aria-modal="true" aria-label={editingAgent ? '编辑智能体' : '新建智能体'}>
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="agent-config-modal w-full"
              onClick={e => e.stopPropagation()}
            >
              <div className="agent-config-header flex items-center justify-between">
                  <h3 className="font-display text-lg font-semibold text-ink-primary">
                    {editingAgent ? '编辑智能体' : '新建智能体'}
                  </h3>
                  <button onClick={closeModal} aria-label="关闭" className="text-ink-muted hover:text-ink-body transition-colors">
                    <X size={20} aria-hidden="true" />
                  </button>
                </div>

                <div className="agent-config-scroll space-y-3.5">

                {/* 模板选择 */}
                {!editingAgent && templates.length > 0 && (
                  <div>
                    <label className="text-xs text-ink-muted mb-2 block">从模板创建</label>
                    <div className="flex gap-2 flex-wrap">
                      {templates.map(tpl => (
                        <button key={tpl.id}
                          onClick={() => applyTemplate(tpl)}
                          className={`px-3 py-1.5 rounded-xl text-xs border transition-all ${
                            form.template_id === tpl.id
                              ? 'border-sky-300 bg-sky-50 text-sky-600 shadow-cloud-sm'
                              : 'border-cloud-300 text-ink-muted hover:border-cloud-400 hover:text-ink-body'
                          }`}>
                          {tpl.icon} {tpl.name.replace(/^[^一-龥]*\s*/, '')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* 基础信息 */}
                <div className="grid grid-cols-4 gap-3">
                  <div className="col-span-1">
                    <label className="text-xs text-ink-muted mb-1 block">图标</label>
                    <input className="input-field text-center text-2xl py-1" value={form.icon}
                      onChange={e => setForm({ ...form, icon: e.target.value })} maxLength={4} />
                  </div>
                  <div className="col-span-3">
                    <label className="text-xs text-ink-muted mb-1 block">名称</label>
                    <input className="input-field" placeholder="智能体名称" value={form.name}
                      onChange={e => {
                        setNameTouched(true)
                        setFormError('')
                        setForm({ ...form, name: e.target.value })
                      }} />
                    {nameError && (
                      <p className="mt-1 text-2xs text-rose-600">{nameError}</p>
                    )}
                  </div>
                </div>

                <div>
                  <label className="text-xs text-ink-muted mb-1 block">描述</label>
                  <input className="input-field" placeholder="简短描述智能体的用途" value={form.description}
                    onChange={e => setForm({ ...form, description: e.target.value })} />
                </div>

                <div>
                  <label className="text-xs text-ink-muted mb-1 block">欢迎语</label>
                  <input className="input-field" placeholder="进入对话时显示的欢迎消息" value={form.welcome_message}
                    onChange={e => setForm({ ...form, welcome_message: e.target.value })} />
                </div>

                {/* 知识库与模型 */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-ink-muted mb-1 block">关联知识库</label>
                    <select className="input-field" value={form.kb_name}
                      onChange={e => setForm({ ...form, kb_name: e.target.value })}>
                      {kbs.map(kb => <option key={kb.name} value={kb.name}>{kb.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-ink-muted mb-1 block">LLM 模型</label>
                    <select className="input-field" value={form.llm_model}
                      onChange={e => setForm({ ...form, llm_model: e.target.value })}>
                      <option value="qwen-plus">qwen-plus（推荐）</option>
                      <option value="qwen-turbo">qwen-turbo（快速省钱）</option>
                      <option value="qwen-max">qwen-max（最强）</option>
                      <option value="qwen3-32b">qwen3-32b</option>
                    </select>
                  </div>
                </div>

                {/* 查询模式 */}
                <div>
                  <label className="text-xs text-ink-muted mb-1 block">默认查询模式</label>
                  <select className="input-field" value={form.query_mode}
                    onChange={e => setForm({ ...form, query_mode: e.target.value })}>
                    <option value="rrf">融合检索 RRF</option>
                    <option value="hybrid">混合检索（推荐）</option>
                    <option value="local">精确检索</option>
                    <option value="global">全局检索</option>
                    <option value="naive">快速检索</option>
                  </select>
                </div>

                {/* 推理模式 */}
                <div>
                  <label className="text-xs text-ink-muted mb-1 block">推理模式</label>
                  <select className="input-field" value={form.agent_mode}
                    onChange={e => setForm({ ...form, agent_mode: e.target.value })}>
                    <option value="none">无（直接回答）</option>
                    <option value="react">ReAct 多步推理</option>
                    <option value="cot">CoT 逐步思考</option>
                  </select>
                </div>

                {/* 温度参数 */}
                <div>
                  <div className="flex justify-between">
                    <label className="text-xs text-ink-muted mb-1 block">回复温度</label>
                    <span className="text-2xs font-mono text-sky-500">{form.temperature.toFixed(1)}</span>
                  </div>
                  <input type="range" min="0" max="1.5" step="0.1" value={form.temperature}
                    onChange={e => setForm({ ...form, temperature: parseFloat(e.target.value) })}
                    className="w-full accent-sky-500" />
                  <div className="flex justify-between text-2xs text-ink-muted">
                    <span>严谨 (0)</span><span>平衡</span><span>创意 (1.5)</span>
                  </div>
                </div>

                {/* 生成与检索参数 */}
                <div className="rounded-xl border border-cloud-300 bg-cloud-50/70 p-3 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <label className="text-xs font-semibold text-ink-primary">生成与检索参数</label>
                    <span className="text-2xs text-ink-muted">保存后影响对话生成与知识库检索</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <div>
                      <label className="text-2xs text-ink-muted mb-1 block">最大回复 tokens</label>
                      <input className="input-field text-sm" type="number" min="512" max="16384" step="256" value={form.max_response_tokens}
                        onChange={e => setForm({ ...form, max_response_tokens: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-2xs text-ink-muted mb-1 block">检索召回数</label>
                      <input className="input-field text-sm" type="number" min="5" max="200" step="5" value={form.retrieval_top_k}
                        onChange={e => setForm({ ...form, retrieval_top_k: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-2xs text-ink-muted mb-1 block">Chunk 候选数</label>
                      <input className="input-field text-sm" type="number" min="1" max="100" step="1" value={form.chunk_top_k}
                        onChange={e => setForm({ ...form, chunk_top_k: e.target.value })} />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <button type="button" onClick={() => setForm({ ...form, enable_rerank: !form.enable_rerank })}
                      className={`rounded-xl border px-3 py-2 text-left transition-all ${form.enable_rerank ? 'border-sky-300 bg-sky-50 text-sky-700' : 'border-cloud-300 bg-white text-ink-body hover:bg-cloud-100'}`}>
                      <span className="block text-xs font-semibold">启用重排</span>
                      <span className="mt-1 block text-2xs text-ink-muted">提升精度，可能增加响应时间</span>
                    </button>
                    <button type="button" onClick={() => setForm({ ...form, include_references: !form.include_references })}
                      className={`rounded-xl border px-3 py-2 text-left transition-all ${form.include_references ? 'border-sky-300 bg-sky-50 text-sky-700' : 'border-cloud-300 bg-white text-ink-body hover:bg-cloud-100'}`}>
                      <span className="block text-xs font-semibold">包含引用来源</span>
                      <span className="mt-1 block text-2xs text-ink-muted">控制回答提示词和参考来源回填</span>
                    </button>
                  </div>
                </div>

                {/* 系统提示词 */}
                <div>
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <label className="text-xs text-ink-muted block">回答风格</label>
                    <span className="text-2xs text-ink-muted">写入系统提示词，保存后生效</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {ANSWER_STYLE_PRESETS.map(preset => {
                      const isActive = activeAnswerStyle?.id === preset.id
                      return (
                        <button
                          key={preset.id}
                          type="button"
                          onClick={() => applyAnswerStyle(preset)}
                          className={`text-left rounded-xl border px-3 py-2 transition-all ${
                            isActive
                              ? 'border-sky-300 bg-sky-50 text-sky-700 shadow-cloud-sm'
                              : 'border-cloud-300 bg-white text-ink-body hover:border-sky-200 hover:bg-sky-50/60'
                          }`}
                        >
                          <span className="block text-xs font-semibold">{preset.label}</span>
                          <span className="mt-1 block text-2xs leading-relaxed text-ink-muted">{preset.description}</span>
                        </button>
                      )
                    })}
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-3 text-2xs text-ink-muted">
                    <span>{activeAnswerStyle ? `当前：${activeAnswerStyle.label}` : '当前：自定义或未设置'}</span>
                    <button type="button" onClick={clearAnswerStyle} className="text-sky-600 hover:text-sky-700 transition-colors">
                      清空提示词
                    </button>
                  </div>
                </div>

                <div>
                  <label className="text-xs text-ink-muted mb-1 block">自定义系统提示词</label>
                  <textarea className="input-field h-28 text-xs font-mono" placeholder="可直接编辑回答风格或智能体行为指令..."
                    value={form.system_prompt}
                    onChange={e => setForm({ ...form, system_prompt: e.target.value })} />
                  <p className="mt-1 text-2xs text-ink-muted">此内容会作为对话链路的 system_prompt 使用，不会新增未接线的配置字段。</p>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setForm({ ...form, use_default_prompt: !form.use_default_prompt })}
                    className={`relative w-10 h-5 rounded-full transition-colors ${form.use_default_prompt ? 'bg-sky-500' : 'bg-cloud-300'}`}>
                    <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform"
                      style={{ left: form.use_default_prompt ? '1.25rem' : '0.125rem' }} />
                  </button>
                  <span className="text-xs text-ink-muted">叠加默认格式化提示词（标题、列表、表格结构）</span>
                </div>

                {/* 操作按钮 */}
                </div>

                {formError && (
                  <div className="mx-6 mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
                    {formError}
                  </div>
                )}

                <div className="agent-config-footer flex gap-3">
                  <button
                    onClick={saveAgent}
                    className="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={saving || !form.name.trim()}
                  >
                    {saving ? '保存中...' : editingAgent ? '保存修改' : '创建智能体'}
                  </button>
                  <button onClick={closeModal} className="btn-secondary" disabled={saving}>取消</button>
                </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>,
      document.body
      )}

      {/* 删除确认 */}
      <AnimatePresence>
        {deleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-sky-900/25 dark:bg-black/40 backdrop-blur-sm" onClick={() => setDeleteConfirm(null)} role="dialog" aria-modal="true" aria-label="确认删除智能体">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="card p-6 max-w-sm w-full m-4"
              onClick={e => e.stopPropagation()}
            >
              <h3 className="font-medium text-ink-primary mb-2">确认删除智能体？</h3>
              <p className="text-sm text-ink-muted mb-4">删除后对话历史将永久丢失，关联的知识库不受影响。</p>
              <div className="flex gap-3">
                <button onClick={() => deleteAgent(deleteConfirm)} className="flex-1 py-2 rounded-xl bg-rose-50 text-rose-600 border border-rose-200 text-sm hover:bg-rose-100 transition-colors">确认删除</button>
                <button onClick={() => setDeleteConfirm(null)} className="flex-1 py-2 rounded-xl bg-cloud-100 text-ink-muted text-sm hover:bg-cloud-300 transition-colors">取消</button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  )
}
