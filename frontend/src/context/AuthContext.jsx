import { createContext, useContext, useState, useEffect, useCallback } from 'react'

import { synchronizeSystemDataEpoch } from '../utils/systemDataEpoch'
import { advanceKnowledgeDetailAuthGeneration } from '../utils/api'
import {
  readStoredAuth,
  writeStoredAuth,
  removeStoredAuth,
  refreshStoredSession,
} from '../utils/authSession'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)

  // 从本地存储恢复登录状态，并验证令牌有效性。
  useEffect(() => {
    let cancelled = false
    const init = async () => {
      const saved = readStoredAuth()
      if (saved?.token) {
        try {
          const res = await fetch('/api/auth/me', {
            headers: { 'Authorization': `Bearer ${saved.token}` },
          })
          if (res.ok) {
            const me = await res.json()
            if (!cancelled) {
              writeStoredAuth({
                access_token: saved.token,
                refresh_token: saved.refreshToken,
                user: me.user,
              })
              advanceKnowledgeDetailAuthGeneration()
              setToken(saved.token)
              setUser(me.user)
            }
          } else if (res.status === 401 || res.status === 403) {
            const refreshed = await refreshStoredSession()
            if (refreshed && !cancelled) {
              advanceKnowledgeDetailAuthGeneration()
              setToken(refreshed.access_token)
              setUser(refreshed.user)
            } else if (!refreshed && !cancelled) {
              advanceKnowledgeDetailAuthGeneration()
              setToken(null)
              setUser(null)
              removeStoredAuth()
            }
          }
        } catch { /* 网络/5xx 不清除持久 refresh，会在下次加载时重试 */ }
      }
      if (!cancelled) {
        setLoading(false)
      }
    }
    init()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const onRefreshed = event => {
      const data = event.detail
      if (!data?.access_token || !data?.user) return
      advanceKnowledgeDetailAuthGeneration()
      setToken(data.access_token)
      setUser(data.user)
    }
    const onExpired = () => {
      advanceKnowledgeDetailAuthGeneration()
      setToken(null)
      setUser(null)
    }
    window.addEventListener('raganything:auth-refreshed', onRefreshed)
    window.addEventListener('raganything:auth-expired', onExpired)
    return () => {
      window.removeEventListener('raganything:auth-refreshed', onRefreshed)
      window.removeEventListener('raganything:auth-expired', onExpired)
    }
  }, [])

  const saveAuth = useCallback((t, rt, u) => {
    advanceKnowledgeDetailAuthGeneration()
    setToken(t)
    setUser(u)
    writeStoredAuth({ access_token: t, refresh_token: rt, user: u })
  }, [])

  const clearAuth = useCallback(() => {
    advanceKnowledgeDetailAuthGeneration()
    setToken(null)
    setUser(null)
    removeStoredAuth()
  }, [])

  const login = useCallback(async (username, password) => {
    await synchronizeSystemDataEpoch()
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '登录失败' }))
      throw new Error(err.detail || '登录失败')
    }
    const data = await res.json()

    // 登录响应必须包含完整角色权限；旧服务端响应不完整时只做一次
    // 权威 /me 获取，失败则不把 partial user 写入本地会话。
    let fullUser = data.user
    if (!fullUser?.role) {
      const meRes = await fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${data.access_token}` },
      })
      if (!meRes.ok) throw new Error('登录会话信息不完整，请重试')
      fullUser = (await meRes.json()).user
    }
    if (!fullUser?.role) throw new Error('登录会话信息不完整，请重试')

    saveAuth(data.access_token, data.refresh_token, fullUser)
    return { ...data, user: fullUser }
  }, [saveAuth])

  const logout = useCallback(async () => {
    try {
      if (token) {
        const saved = readStoredAuth()
        const refreshToken = saved?.refreshToken || null
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      }
    } catch { /* 无需处理 */ } finally {
      clearAuth()
    }
  }, [token, clearAuth])

  // 验证令牌是否仍然有效
  const verifyToken = useCallback(async () => {
    if (!token) return false
    let res
    try {
      res = await fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setUser(data.user)
        return true
      }
    } catch { return false }
    if (res.status === 401 || res.status === 403) clearAuth()
    return false
  }, [token, clearAuth])

  const isAdmin = user?.role?.name === 'super_admin'

  // 权限集（从 JWT 或角色中解析）
  const permissions = user?.role?.permissions || []

  // 权限检查：用户拥有指定权限则返回 true；管理员自动拥有所有权限
  const hasPermission = useCallback((perm) => {
    if (isAdmin) return true
    if (!perm) return true
    return Array.isArray(permissions) && permissions.includes(perm)
  }, [isAdmin, permissions])

  // 角色名快捷访问
  const roleName = user?.role?.name || null

  return (
    <AuthContext.Provider value={{ user, token, loading, isAdmin, permissions, roleName, hasPermission, login, logout, verifyToken, saveAuth, clearAuth }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export default AuthContext
