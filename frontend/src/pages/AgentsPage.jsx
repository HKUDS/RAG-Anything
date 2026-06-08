import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Plus, Bot, Trash2, Edit3, X, MessageSquare, Database,
  Cpu, Search, Zap, Copy, ChevronDown
} from 'lucide-react'
import { api } from '../utils/api'
import { motion, AnimatePresence } from 'framer-motion'

const MODE_LABELS = { hybrid: '混合', local: '精确', global: '全局', naive: '快速' }

export default function AgentsPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState([])
  const [templates, setTemplates] = useState([])
  const [kbs, setKBs] = useState([])
  const [showModal, setShowModal] = useState(false)
  const [editingAgent, setEditingAgent] = useState(null)
  const [form, setForm] = useState(getDefaultForm())
  const [deleteConfirm, setDeleteConfirm] = useState(null)

  useEffect(() => { loadData() }, [])

  function getDefaultForm() {
    return {
      name: '', icon: '🤖', description: '', kb_name: 'default', llm_model: 'qwen-plus',
      temperature: 0.0, query_mode: 'hybrid',
      system_prompt: '', use_default_prompt: true, welcome_message: '', template_id: '',
    }
  }

  const loadData = () => {
    api.listAgents().then(r => setAgents(r.agents || [])).catch(() => {})
    api.getAgentTemplates().then(r => setTemplates(r.templates || [])).catch(() => {})
    api.listKBs().then(r => setKBs(r.knowledge_bases || [])).catch(() => {})
  }

  const openCreate = () => {
    setEditingAgent(null)
    setForm(getDefaultForm())
    setShowModal(true)
  }

  const openEdit = (agent) => {
    setEditingAgent(agent.id)
    setForm({
      name: agent.name, icon: agent.icon || '🤖', description: agent.description || '',
      kb_name: agent.kb_name, llm_model: agent.llm_model, temperature: agent.temperature || 0,
      query_mode: agent.query_mode,
      system_prompt: agent.system_prompt || '', use_default_prompt: agent.use_default_prompt !== false,
      welcome_message: agent.welcome_message || '', template_id: agent.template_id || '',
    })
    setShowModal(true)
  }

  const applyTemplate = (tpl) => {
    setForm({
      ...form,
      name: tpl.name.replace(/^[^一-龥]*\s*/, ''),
      icon: tpl.icon || '🤖',
      description: tpl.description || '',
      llm_model: tpl.llm_model || 'qwen-plus',
      temperature: tpl.temperature ?? 0,
      query_mode: tpl.query_mode || 'hybrid',
      system_prompt: tpl.system_prompt || '',
      use_default_prompt: tpl.use_default_prompt !== false,
      welcome_message: tpl.welcome_message || '',
      template_id: tpl.id,
    })
  }

  const saveAgent = async () => {
    if (!form.name.trim()) return
    try {
      if (editingAgent) {
        await api.updateAgent(editingAgent, form)
      } else {
        await api.createAgent(form)
      }
      setShowModal(false)
      loadData()
    } catch (e) {
      console.error('保存智能体失败:', e)
    }
  }

  const deleteAgent = async (id) => {
    await api.deleteAgent(id)
    setDeleteConfirm(null)
    loadData()
  }

  const startChat = (agent) => {
    navigate(`/agents/${agent.id}`)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-xl font-bold text-slate-100">智能体</h2>
          <p className="text-sm text-slate-500 mt-1">每个智能体拥有独立的知识库、模型和对话配置</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> 新建智能体
        </button>
      </div>

      {/* Agent Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {agents.map(agent => (
          <motion.div
            key={agent.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass p-5 group cursor-pointer hover:border-neon-500/20 transition-all"
            onClick={() => startChat(agent)}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className="text-3xl">{agent.icon || '🤖'}</span>
                <div>
                  <h3 className="font-medium text-slate-200 text-sm">{agent.name}</h3>
                  <p className="text-[11px] text-slate-600 font-mono">ID: {agent.id}</p>
                </div>
              </div>
              <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                <button className="p-1.5 rounded text-slate-500 hover:text-neon-400 hover:bg-slate-800/50" onClick={() => openEdit(agent)}>
                  <Edit3 size={14} />
                </button>
                <button className="p-1.5 rounded text-slate-500 hover:text-red-400 hover:bg-slate-800/50" onClick={() => setDeleteConfirm(agent.id)}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            {agent.description && (
              <p className="text-xs text-slate-500 mb-3 line-clamp-2">{agent.description}</p>
            )}

            {/* Config tags */}
            <div className="flex flex-wrap gap-1.5 mb-3">
              <span className="tag tag-purple">
                <Database size={10} /> {agent.kb_name}
              </span>
              <span className="tag tag-blue">
                <Cpu size={10} /> {agent.llm_model}
              </span>
              <span className="tag tag-amber">
                <Search size={10} /> {MODE_LABELS[agent.query_mode] || agent.query_mode}
              </span>
            </div>

            {/* Start chat button */}
            <button className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-neon-500/10 text-neon-400 text-xs font-medium hover:bg-neon-500/20 transition-colors">
              <MessageSquare size={13} /> 开始对话
            </button>
          </motion.div>
        ))}
      </div>

      {agents.length === 0 && (
        <div className="text-center py-20">
          <Bot size={48} className="mx-auto mb-3 text-slate-700" />
          <p className="text-slate-500 text-sm">还没有智能体</p>
          <button onClick={openCreate} className="btn-primary mt-4 text-sm">创建第一个智能体</button>
        </div>
      )}

      {/* Create/Edit Modal */}
      <AnimatePresence>
        {showModal && (
          <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 bg-black/60 backdrop-blur-sm" onClick={() => setShowModal(false)}>
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="glass w-full max-w-2xl max-h-[80vh] overflow-y-auto m-4"
              onClick={e => e.stopPropagation()}
            >
              <div className="p-6 space-y-5">
                <div className="flex items-center justify-between">
                  <h3 className="font-display text-lg font-bold text-slate-100">
                    {editingAgent ? '编辑智能体' : '新建智能体'}
                  </h3>
                  <button onClick={() => setShowModal(false)} className="text-slate-500 hover:text-slate-300">
                    <X size={20} />
                  </button>
                </div>

                {/* Template Selection */}
                {!editingAgent && templates.length > 0 && (
                  <div>
                    <label className="text-xs text-slate-500 mb-2 block">从模板创建</label>
                    <div className="flex gap-2 flex-wrap">
                      {templates.map(tpl => (
                        <button key={tpl.id}
                          onClick={() => applyTemplate(tpl)}
                          className={`px-3 py-1.5 rounded-lg text-xs border transition-all ${
                            form.template_id === tpl.id
                              ? 'border-neon-500/40 bg-neon-500/10 text-neon-400'
                              : 'border-slate-700/50 text-slate-500 hover:border-slate-600'
                          }`}>
                          {tpl.icon} {tpl.name.replace(/^[^一-龥]*\s*/, '')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Basic Info */}
                <div className="grid grid-cols-4 gap-3">
                  <div className="col-span-1">
                    <label className="text-xs text-slate-500 mb-1 block">图标</label>
                    <input className="input-field text-center text-2xl py-1" value={form.icon}
                      onChange={e => setForm({ ...form, icon: e.target.value })} maxLength={4} />
                  </div>
                  <div className="col-span-3">
                    <label className="text-xs text-slate-500 mb-1 block">名称</label>
                    <input className="input-field" placeholder="智能体名称" value={form.name}
                      onChange={e => setForm({ ...form, name: e.target.value })} />
                  </div>
                </div>

                <div>
                  <label className="text-xs text-slate-500 mb-1 block">描述</label>
                  <input className="input-field" placeholder="简短描述智能体的用途" value={form.description}
                    onChange={e => setForm({ ...form, description: e.target.value })} />
                </div>

                <div>
                  <label className="text-xs text-slate-500 mb-1 block">欢迎语</label>
                  <input className="input-field" placeholder="进入对话时显示的欢迎消息" value={form.welcome_message}
                    onChange={e => setForm({ ...form, welcome_message: e.target.value })} />
                </div>

                {/* KB + Model */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-500 mb-1 block">关联知识库</label>
                    <select className="input-field" value={form.kb_name}
                      onChange={e => setForm({ ...form, kb_name: e.target.value })}>
                      {kbs.map(kb => <option key={kb.name} value={kb.name}>{kb.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-500 mb-1 block">LLM 模型</label>
                    <select className="input-field" value={form.llm_model}
                      onChange={e => setForm({ ...form, llm_model: e.target.value })}>
                      <option value="qwen-plus">qwen-plus（推荐）</option>
                      <option value="qwen-turbo">qwen-turbo（快速省钱）</option>
                      <option value="qwen-max">qwen-max（最强）</option>
                      <option value="qwen3-32b">qwen3-32b</option>
                    </select>
                  </div>
                </div>

                {/* Query Mode */}
                <div>
                  <label className="text-xs text-slate-500 mb-1 block">默认查询模式</label>
                  <select className="input-field" value={form.query_mode}
                    onChange={e => setForm({ ...form, query_mode: e.target.value })}>
                      <option value="hybrid">混合检索（推荐）</option>
                      <option value="local">精确检索</option>
                      <option value="global">全局检索</option>
                      <option value="naive">快速检索</option>
                    </select>
                  </div>

                {/* Temperature */}
                <div>
                  <div className="flex justify-between">
                    <label className="text-xs text-slate-500 mb-1 block">回复温度</label>
                    <span className="text-[10px] font-mono text-neon-400">{form.temperature.toFixed(1)}</span>
                  </div>
                  <input type="range" min="0" max="1.5" step="0.1" value={form.temperature}
                    onChange={e => setForm({ ...form, temperature: parseFloat(e.target.value) })}
                    className="w-full accent-neon-500" />
                  <div className="flex justify-between text-[10px] text-slate-600">
                    <span>严谨 (0)</span><span>平衡</span><span>创意 (1.5)</span>
                  </div>
                </div>

                {/* System Prompt */}
                <div>
                  <label className="text-xs text-slate-500 mb-1 block">系统提示词</label>
                  <textarea className="input-field h-24 text-xs font-mono" placeholder="自定义智能体行为指令..."
                    value={form.system_prompt}
                    onChange={e => setForm({ ...form, system_prompt: e.target.value })} />
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setForm({ ...form, use_default_prompt: !form.use_default_prompt })}
                    className={`relative w-10 h-5 rounded-full transition-colors ${form.use_default_prompt ? 'bg-neon-500' : 'bg-slate-700'}`}>
                    <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
                      style={{ left: form.use_default_prompt ? '1.25rem' : '0.125rem' }} />
                  </button>
                  <span className="text-xs text-slate-400">叠加默认格式化提示词（标题、列表、表格结构）</span>
                </div>

                {/* Action buttons */}
                <div className="flex gap-3 pt-2">
                  <button onClick={saveAgent} className="btn-primary flex-1">
                    {editingAgent ? '保存修改' : '创建智能体'}
                  </button>
                  <button onClick={() => setShowModal(false)} className="btn-ghost">取消</button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Delete Confirmation */}
      <AnimatePresence>
        {deleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setDeleteConfirm(null)}>
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="glass p-6 max-w-sm w-full m-4"
              onClick={e => e.stopPropagation()}
            >
              <h3 className="font-medium text-slate-200 mb-2">确认删除智能体？</h3>
              <p className="text-sm text-slate-500 mb-4">删除后对话历史将永久丢失，关联的知识库不受影响。</p>
              <div className="flex gap-3">
                <button onClick={() => deleteAgent(deleteConfirm)} className="flex-1 py-2 rounded-lg bg-red-500/20 text-red-400 text-sm">确认删除</button>
                <button onClick={() => setDeleteConfirm(null)} className="flex-1 py-2 rounded-lg bg-slate-800 text-slate-400 text-sm">取消</button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  )
}
