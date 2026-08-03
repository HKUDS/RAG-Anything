import { Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { resolveDeniedRoute } from '../utils/settingsRouting'

/**
 * Authenticated route guard. Denied routes recover silently to the first
 * readable destination instead of exposing permission internals.
 */
export default function ProtectedRoute({ children, adminOnly = false, requiredPermission = null }) {
  const { token, loading, hasPermission } = useAuth()
  const location = useLocation()

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

  const permission = requiredPermission || (adminOnly ? 'users:read' : null)
  if (permission && !hasPermission(permission)) {
    return <Navigate replace to={resolveDeniedRoute(hasPermission, location.pathname)} />
  }

  return children
}
