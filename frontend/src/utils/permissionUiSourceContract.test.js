import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

const ordinaryPages = [
  '../components/ProtectedRoute.jsx',
  '../pages/AgentsPage.jsx',
  '../pages/KnowledgePage.jsx',
  '../pages/KnowledgeDetailPage.jsx',
  '../pages/DocumentChunksPage.jsx',
  '../pages/DocumentChunkDetailPage.jsx',
  '../pages/AgentChatPage.jsx',
  '../pages/WorkflowPage.jsx',
  '../pages/MonitorPage.jsx',
  '../pages/AutoRepairDashboardPage.jsx',
  '../pages/AutoRepairKnowledgePage.jsx',
  '../pages/AutoRepairAgentPage.jsx',
]

test('ordinary business pages do not disclose routine permission or read-only reasons', () => {
  const combined = ordinaryPages.map(source).join('\n')
  for (const forbidden of ['只读模式', '需要 settings:write', '需要 kb:write', '无 autorepair:write 权限', '无 workflow:write 权限', '无权访问']) {
    assert.equal(combined.includes(forbidden), false, `found forbidden ordinary-page copy: ${forbidden}`)
  }
  assert.doesNotMatch(combined, /disabled=\{!can[A-Z]/)
  assert.doesNotMatch(combined, /isAdmin\s*\|\|\s*hasPermission/)
})

test('workflow read-only mode is fail-closed across toolbar, canvas and node uploads', () => {
  const toolbar = source('../components/workflow/WorkflowToolbar.jsx')
  const canvas = source('../components/workflow/WorkflowCanvas.jsx')
  const panel = source('../components/workflow/NodeConfigPanel.jsx')
  const page = source('../pages/WorkflowPage.jsx')
  assert.match(toolbar, /canEdit = false/)
  assert.match(canvas, /nodesDraggable=\{editable\}/)
  assert.match(canvas, /deleteKeyCode=\{editable \?/)
  assert.match(panel, /if \(!canEdit\) return/)
  assert.match(page, /if \(!canEdit\) return/)
  assert.match(page, /\(e\.ctrlKey \|\| e\.metaKey\) && e\.key === 's'/)
  assert.match(toolbar, /e\.key === 'Enter'/)
  assert.match(page, /\{canEdit && <NodePalette/)
})

test('AutoRepair scoped loaders and parser require a confirmed KB', () => {
  const hook = source('../hooks/useAutoRepairKB.js')
  const dashboard = source('../pages/AutoRepairDashboardPage.jsx')
  const knowledge = source('../pages/AutoRepairKnowledgePage.jsx')
  const agent = source('../pages/AutoRepairAgentPage.jsx')
  const editor = source('../components/GCodeEditor.jsx')
  assert.doesNotMatch(hook, /\{ name: 'autorepair'/)
  assert.match(dashboard, /if \(!arKb\)/)
  assert.match(knowledge, /if \(!arKb\)/)
  assert.match(agent, /if \(!canInteract \|\| !arKb\) return/)
  assert.match(editor, /canParse = false/)
  assert.match(hook, /generation !== requestGeneration\.current/)
  assert.match(hook, /rejectAutoRepairKbSelection/)
  assert.match(dashboard, /AutoRepairKBState error=\{kbError\}/)
})

test('direct knowledge routes confirm list membership before scoped requests', () => {
  const detail = source('../pages/KnowledgeDetailPage.jsx')
  const chunks = source('../pages/DocumentChunksPage.jsx')
  const chunk = source('../pages/DocumentChunkDetailPage.jsx')
  for (const page of [detail, chunks, chunk]) {
    assert.match(page, /useConfirmedKnowledgeBase\(kbName\)/)
    assert.match(page, /kbAccess\.confirmed/)
  }
  assert.doesNotMatch(chunks, /setCurrentKB\(kbName\)/)
  assert.doesNotMatch(chunk, /setCurrentKB\(kbName\)/)
})

test('stale write handlers fail closed after live permission revocation', () => {
  const knowledge = source('../pages/KnowledgePage.jsx')
  const chunk = source('../pages/DocumentChunkDetailPage.jsx')
  const chat = source('../pages/AgentChatPage.jsx')
  assert.match(knowledge, /if \(!canCreateKB\) return/)
  assert.match(knowledge, /if \(!canDeleteKB\) return/)
  assert.match(chunk, /if \(!canWrite \|\| !kbAccess\.confirmed/)
  assert.match(chat, /if \(!canEditMessages\) return/)
})

test('App routes and copy are capability-aware', () => {
  const app = source('../App.jsx')
  assert.match(app, /path="\/knowledge" element=\{<ProtectedRoute requiredPermission="kb:read"/)
  assert.match(app, /path="\/autorepair\/agent" element=\{<ProtectedRoute requiredPermission="autorepair:write"/)
  assert.match(app, /policy\.canWriteAgents \? '可配置' : '可使用'/)
  assert.match(app, /policy\.canWriteSettings \? '可配置' : '可查看'/)
})
