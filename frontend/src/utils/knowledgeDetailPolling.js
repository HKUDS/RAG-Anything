import { getUploadTaskStatus } from './documentHealth.js'

// 与详情页既有常量保持一致：这些状态代表上传任务已不再占用后端处理。
const UPLOAD_TASK_TERMINAL_STATUSES = new Set(['completed', 'processed', 'failed', 'degraded'])

export function isTerminalUploadTask(task) {
  return UPLOAD_TASK_TERMINAL_STATUSES.has(getUploadTaskStatus(task))
}

export function hasActiveUploadTasks(tasks) {
  return Array.isArray(tasks) && tasks.some(task => !isTerminalUploadTask(task))
}

// 核心数据轮询门控：仅在页面可见且存在非终态上传任务时才需要刷新核心数据。
// activeTab 暂不参与门控（图谱刷新在 tick 内由调用方按 activeTab 决定），
// 保留该参数以便后续按标签扩展策略。
export function shouldPollCoreData({ visible, hasActiveUploads, activeTab }) {
  void activeTab
  return Boolean(visible && hasActiveUploads)
}

// 上传任务从“存在非终态”变为“全部终态（或空）”时返回 true，
// 用于触发最后一次核心数据刷新，避免文档列表停在旧状态。
export function tasksTransitionedToTerminal(prevTasks, nextTasks) {
  const prev = Array.isArray(prevTasks) ? prevTasks : []
  const next = Array.isArray(nextTasks) ? nextTasks : []
  const hadActive = prev.some(task => !isTerminalUploadTask(task))
  const hasActive = next.some(task => !isTerminalUploadTask(task))
  return hadActive && !hasActive
}
