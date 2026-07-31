import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Loader2, ShieldOff } from 'lucide-react'
import { deniedRouteRecovery } from '../utils/settingsRouting'

/**
 * 路由守卫组件。
 *
 * Props:
 *   requiredPermission — 权限字符串（如 "users:read"、"settings:write"）
 *   adminOnly          — 向后兼容，等价于 requiredPermission="users:read"（管理员权限）
 *   fallback           — 无权限时渲染的内容（默认重定向到首页）
 *
 * 优先级: requiredPermission > adminOnly
 */
export default function ProtectedRoute({ children, adminOnly = false, requiredPermission = null }) {
  const { token, loading, hasPermission } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-cloud-100">
        <Loader2 size={32} className="animate-spin text-sky-500" />
      </div>
    )
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  // 权限检查：优先使用 requiredPermission
  const permToCheck = requiredPermission || (adminOnly ? 'users:read' : null)
  if (permToCheck && !hasPermission(permToCheck)) {
    // 如果用户已登录但无权限，显示 403 而非静默重定向
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <div className="w-14 h-14 rounded-2xl bg-rose-50 flex items-center justify-center">
          <ShieldOff size={24} className="text-rose-400" />
        </div>
        <div className="text-center space-y-1">
          <h2 className="text-lg font-semibold text-ink-primary">访问被拒绝</h2>
          <p className="text-sm text-ink-muted max-w-xs">
            你的角色没有访问此页面的权限。如需访问，请联系系统管理员。
          </p>
          <p className="text-xs text-ink-muted font-mono">需要权限: {permToCheck}</p>
        </div>
        <button type="button" onClick={() => navigate(deniedRouteRecovery, { replace: true })} className="btn-secondary text-xs px-4 py-2">
          前往个人设置
        </button>
      </div>
    )
  }

  return children
}
