import { useState, useCallback, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  addEdge,
  MarkerType,
} from '@xyflow/react'
import WorkflowCanvas from '../components/workflow/WorkflowCanvas'
import NodePalette from '../components/workflow/NodePalette'
import WorkflowToolbar from '../components/workflow/WorkflowToolbar'
import NodeConfigPanel from '../components/workflow/NodeConfigPanel'
import { useAuth } from '../context/AuthContext'

const API = '/api/workflows'

const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#94a3b8', strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8', width: 16, height: 16 },
}

function getToken() {
  try {
    const saved = localStorage.getItem('raganything_auth')
    return saved ? JSON.parse(saved).token : ''
  } catch { return '' }
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' }
}

function ConfirmDialog({ title, message, onConfirm, onCancel }) {
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center"
      onClick={onCancel}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
        className="bg-white rounded-2xl shadow-warm-xl p-6 w-full max-w-sm"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-warm-800 mb-2">{title}</h3>
        <p className="text-sm text-warm-500 mb-5">{message}</p>
        <div className="flex gap-3 justify-end">
          <button onClick={onCancel} className="px-4 py-2 text-sm font-medium rounded-xl bg-warm-100 text-warm-600 hover:bg-warm-200 transition-colors">取消</button>
          <button onClick={onConfirm} className="px-4 py-2 text-sm font-medium rounded-xl bg-coral-500 text-white hover:bg-coral-600 transition-colors">确认</button>
        </div>
      </motion.div>
    </motion.div>
  )
}

function WorkflowPageInner() {
  const { token } = useAuth()
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const { fitView, zoomIn, zoomOut, getZoom, undo, redo } = useReactFlow()
  const isDirty = useRef(false)

  const [selectedNode, setSelectedNode] = useState(null)
  const [workflowName, setWorkflowName] = useState('未命名工作流')
  const [workflowId, setWorkflowId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showLoadDialog, setShowLoadDialog] = useState(false)
  const [workflowList, setWorkflowList] = useState([])
  const [toast, setToast] = useState(null)
  const [zoomLevel, setZoomLevel] = useState(100)

  // Confirm dialogs
  const [confirm, setConfirm] = useState(null)

  // Mark dirty on changes
  const markDirty = useCallback(() => { isDirty.current = true }, [])
  const markClean = useCallback(() => { isDirty.current = false }, [])

  // Toast with cleanup
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 2500)
    return () => clearTimeout(timer)
  }, [toast])

  const showToast = (msg, type = 'info') => setToast({ msg, type })

  // Zoom tracking
  useEffect(() => {
    const interval = setInterval(() => {
      const z = getZoom()
      if (z) setZoomLevel(Math.round(z * 100))
    }, 200)
    return () => clearInterval(interval)
  }, [getZoom])

  // beforeunload
  useEffect(() => {
    const handler = (e) => {
      if (isDirty.current) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Ctrl+S → save
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        handleSave()
      }
      // Escape → close panel
      if (e.key === 'Escape') {
        if (selectedNode) { setSelectedNode(null); return }
        if (confirm) { setConfirm(null); return }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedNode, confirm, nodes, edges, workflowName, workflowId])

  // Track undo/redo via ReactFlow changes
  const wrappedOnNodesChange = useCallback((changes) => {
    onNodesChange(changes)
    markDirty()
  }, [onNodesChange, markDirty])

  const wrappedOnEdgesChange = useCallback((changes) => {
    onEdgesChange(changes)
    markDirty()
  }, [onEdgesChange, markDirty])

  const onConnect = useCallback(
    (connection) => {
      setEdges((eds) => addEdge({ ...connection, ...defaultEdgeOptions }, eds))
      markDirty()
    },
    [setEdges, markDirty]
  )

  const onDropNode = useCallback(
    (newNode) => { setNodes((nds) => [...nds, newNode]); markDirty() },
    [setNodes, markDirty]
  )

  // Save
  const handleSave = async () => {
    if (!token) { showToast('请先登录', 'error'); return }
    if (nodes.length === 0) { showToast('工作流为空，请先添加节点', 'error'); return }
    setSaving(true)
    try {
      const payload = { name: workflowName, nodes, edges }
      const method = workflowId ? 'PUT' : 'POST'
      const url = workflowId ? `${API}/${workflowId}` : API
      const res = await fetch(url, { method, headers: authHeaders(), body: JSON.stringify(payload) })
      if (!res.ok) throw new Error((await res.json().catch(() => ({ detail: '保存失败' }))).detail)
      const data = await res.json()
      if (!workflowId) setWorkflowId(data.id)
      markClean()
      showToast(`"${workflowName}" 已保存`, 'success')
    } catch (e) {
      showToast(e.message || '保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  // New (with confirm)
  const handleNew = () => {
    if (isDirty.current && nodes.length > 0) {
      setConfirm({
        title: '新建工作流',
        message: '当前工作流有未保存的修改，确定放弃并新建？',
        action: () => {
          setNodes([]); setEdges([]); setSelectedNode(null)
          setWorkflowName('未命名工作流'); setWorkflowId(null)
          markClean()
          setConfirm(null)
        },
      })
    } else {
      setNodes([]); setEdges([]); setSelectedNode(null)
      setWorkflowName('未命名工作流'); setWorkflowId(null)
      markClean()
    }
  }

  // Load list
  const handleOpenLoad = async () => {
    if (!token) { showToast('请先登录', 'error'); return }
    try {
      const res = await fetch(API, { headers: authHeaders() })
      if (!res.ok) throw new Error('加载失败')
      const data = await res.json()
      setWorkflowList(data.workflows || [])
      setShowLoadDialog(true)
    } catch (e) {
      showToast('加载列表失败', 'error')
    }
  }

  const handleLoad = async (id) => {
    const doLoad = async () => {
      try {
        const res = await fetch(`${API}/${id}`, { headers: authHeaders() })
        if (!res.ok) throw new Error('加载失败')
        const data = await res.json()
        setWorkflowId(data.id); setWorkflowName(data.name)
        setNodes(data.nodes || []); setEdges(data.edges || [])
        setSelectedNode(null); setShowLoadDialog(false)
        markClean()
        showToast(`"${data.name}" 已加载`, 'success')
      } catch (e) {
        showToast('加载工作流失败', 'error')
      }
    }
    if (isDirty.current && nodes.length > 0) {
      setConfirm({ title: '加载工作流', message: '当前工作流有未保存的修改，确定放弃并加载？', action: async () => { setConfirm(null); await doLoad() } })
    } else {
      await doLoad()
    }
  }

  const handleDelete = async (id, name) => {
    setConfirm({
      title: '删除工作流',
      message: `确定删除 "${name || '未命名'}" 吗？此操作不可撤销。`,
      action: async () => {
        try {
          const res = await fetch(`${API}/${id}`, { method: 'DELETE', headers: authHeaders() })
          if (!res.ok) throw new Error('删除失败')
          setWorkflowList((l) => l.filter((w) => w.id !== id))
          if (workflowId === id) {
            setNodes([]); setEdges([]); setWorkflowName('未命名工作流'); setWorkflowId(null); markClean()
          }
          showToast('已删除', 'success')
        } catch (e) { showToast('删除失败', 'error') }
        setConfirm(null)
      },
    })
  }

  // Node click
  const handleNodeClick = useCallback((node) => setSelectedNode(node), [])

  const handleNodeUpdate = useCallback((nodeId, newData) => {
    setNodes((nds) => nds.map((n) => (n.id === nodeId ? { ...n, data: newData } : n)))
    setSelectedNode((prev) => (prev?.id === nodeId ? { ...prev, data: newData } : prev))
    markDirty()
  }, [setNodes, markDirty])

  // Auto layout
  const handleAutoLayout = () => {
    if (nodes.length === 0) { showToast('没有节点可布局', 'error'); return }
    const GAP_X = 250, GAP_Y = 120
    const inDegree = {}, adj = {}
    nodes.forEach((n) => { inDegree[n.id] = 0; adj[n.id] = [] })
    edges.forEach((e) => {
      inDegree[e.target] = (inDegree[e.target] || 0) + 1
      if (!adj[e.source]) adj[e.source] = []
      adj[e.source].push(e.target)
    })
    const levels = {}
    const queue = nodes.filter((n) => inDegree[n.id] === 0).map((n) => n.id)
    queue.forEach((id) => (levels[id] = 0))
    let ptr = 0
    while (ptr < queue.length) {
      const cur = queue[ptr++]
      for (const next of adj[cur] || []) {
        levels[next] = Math.max(levels[next] || 0, (levels[cur] || 0) + 1)
        inDegree[next]--
        if (inDegree[next] === 0) queue.push(next)
      }
    }
    const byLevel = {}
    nodes.forEach((n) => { const lvl = levels[n.id] ?? 0; (byLevel[lvl] ??= []).push(n) })
    setNodes((nds) => nds.map((n) => {
      const lvl = levels[n.id] ?? 0
      const idx = byLevel[lvl].findIndex(x => x.id === n.id)
      return { ...n, position: { x: 100 + idx * GAP_X, y: 50 + lvl * GAP_Y } }
    }))
    markDirty()
    setTimeout(() => fitView({ duration: 300 }), 50)
    showToast('自动布局完成', 'success')
  }

  const handleFitView = () => fitView({ duration: 300 })

  return (
    <div className="h-[calc(100vh-3.5rem)] flex flex-col">
      <WorkflowToolbar
        workflowName={workflowName}
        onNameChange={(v) => { setWorkflowName(v); markDirty() }}
        onNew={handleNew}
        onSave={handleSave}
        onLoad={handleOpenLoad}
        onAutoLayout={handleAutoLayout}
        onFitView={handleFitView}
        onZoomIn={() => zoomIn({ duration: 200 })}
        onZoomOut={() => zoomOut({ duration: 200 })}
        onUndo={undo}
        onRedo={redo}
        saving={saving}
        isDirty={isDirty.current}
        zoomLevel={zoomLevel}
      />

      <div className="flex-1 flex overflow-hidden">
        <NodePalette />
        <WorkflowCanvas
          nodes={nodes}
          edges={edges}
          onNodesChange={wrappedOnNodesChange}
          onEdgesChange={wrappedOnEdgesChange}
          onConnect={onConnect}
          onNodeClick={handleNodeClick}
          onDropNode={onDropNode}
          onPaneClick={() => setSelectedNode(null)}
        />
        <AnimatePresence>
          {selectedNode && (
            <motion.div
              initial={{ x: 260, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 260, opacity: 0 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className="flex-shrink-0"
            >
              <NodeConfigPanel
                node={selectedNode}
                onClose={() => setSelectedNode(null)}
                onUpdate={handleNodeUpdate}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Load dialog */}
      <AnimatePresence>
        {showLoadDialog && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center"
            onClick={() => setShowLoadDialog(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl shadow-warm-xl p-6 w-full max-w-md"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold text-warm-800 mb-4">加载工作流</h3>
              {workflowList.length === 0 ? (
                <p className="text-sm text-warm-500 text-center py-8">暂无保存的工作流</p>
              ) : (
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {workflowList.map((w) => (
                    <div key={w.id} className="flex items-center justify-between p-3 rounded-xl hover:bg-warm-50 border border-warm-100">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-warm-700 truncate">{w.name}</p>
                        <p className="text-2xs text-warm-400">{new Date(w.updated_at || w.created_at).toLocaleString()}</p>
                      </div>
                      <div className="flex gap-1.5 ml-3">
                        <button onClick={() => handleLoad(w.id)} className="px-3 py-1.5 text-xs font-medium rounded-lg bg-coral-50 text-coral-600 hover:bg-coral-100 transition-colors">加载</button>
                        <button onClick={() => handleDelete(w.id, w.name)} className="px-3 py-1.5 text-xs font-medium rounded-lg bg-rose-50 text-rose-500 hover:bg-rose-100 transition-colors">删除</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <button onClick={() => setShowLoadDialog(false)} className="mt-4 w-full py-2 text-sm text-warm-500 hover:text-warm-700 transition-colors">关闭</button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Confirm dialog */}
      <AnimatePresence>
        {confirm && (
          <ConfirmDialog
            title={confirm.title}
            message={confirm.message}
            onConfirm={confirm.action}
            onCancel={() => setConfirm(null)}
          />
        )}
      </AnimatePresence>

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 24 }}
            className={`fixed bottom-6 right-6 px-5 py-3 rounded-2xl text-sm font-medium z-50 shadow-warm-md ${
              toast.type === 'error' ? 'bg-rose-50 text-rose-600' :
              toast.type === 'success' ? 'bg-emerald-50 text-emerald-600' :
              'bg-warm-50 text-warm-600'
            }`}
          >
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function WorkflowPage() {
  return (
    <ReactFlowProvider>
      <WorkflowPageInner />
    </ReactFlowProvider>
  )
}
