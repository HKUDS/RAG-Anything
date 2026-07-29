import { createContext, useContext, useState, useEffect, useCallback } from 'react'

import { synchronizeSystemDataEpoch } from '../utils/systemDataEpoch'
import { advanceKnowledgeDetailAuthGeneration } from '../utils/api'

const AuthContext = createContext(null)

const AUTH_KEY = 'raganything_auth'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)

// 从本地存储恢复登录状态，并验证令牌有效性
  useEffect(() => {
    let cancelled = false
    const init = async () => {
      try {
        const saved = localStorage.getItem(AUTH_KEY)
        if (saved) {
          const data = JSON.parse(saved)
          // 先尝试用访问令牌验证
          let valid = false
          try {
            const res = await fetch('/api/auth/me', {
              headers: { 'Authorization': `Bearer ${data.token}` },
            })
            if (res.ok) {
              const me = await res.json()
              if (!cancelled) { setToken(data.token); setUser(me.user) }
              valid = true
            }
          } catch (_) {}

          // 访问令牌失效时，尝试用刷新令牌续期
          if (!valid && data.refreshToken) {
            try {
              const refreshRes = await fetch('/api/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: data.refreshToken }),
              })
              if (refreshRes.ok) {
                const refreshed = await refreshRes.json()
                if (!cancelled) {
                  setToken(refreshed.access_token)
                  // 刷新后调用 /auth/me 获取完整用户信息（含角色与权限），
                  // 避免用户为空导致权限判断误判为 403
                  let fullUser = null
                  try {
                    const meRes = await fetch('/api/auth/me', {
                      headers: { 'Authorization': `Bearer ${refreshed.access_token}` },
                    })
                    if (meRes.ok) {
                      const meData = await meRes.json()
                      fullUser = meData.user
                    }
                  } catch (_) {}
                  // 兜底：/me 失败时尝试从本地存储恢复，保持向后兼容
                  if (!fullUser) {
                    try { const s = localStorage.getItem(AUTH_KEY); fullUser = s ? JSON.parse(s).user : null } catch { fullUser = null }
                  }
                  setUser(fullUser)
                  advanceKnowledgeDetailAuthGeneration()
                  localStorage.setItem(AUTH_KEY, JSON.stringify({
                    token: refreshed.access_token,
                    refreshToken: refreshed.refresh_token,
                    user: fullUser,
                  }))
                }
              }
            } catch (_) {}
          }
        }
      } catch { /* 无需处理 */ } finally {
        if (!cancelled) setLoading(false)
      }
    }
    init()
    return () => { cancelled = true }
  }, [])

  const saveAuth = useCallback((t, rt, u) => {
    advanceKnowledgeDetailAuthGeneration()
    setToken(t)
    setUser(u)
    localStorage.setItem(AUTH_KEY, JSON.stringify({ token: t, refreshToken: rt, user: u }))
  }, [])

  const clearAuth = useCallback(() => {
    advanceKnowledgeDetailAuthGeneration()
    setToken(null)
    setUser(null)
    localStorage.removeItem(AUTH_KEY)
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

  // 重新获取完整用户信息（含角色）
    let fullUser = data.user
    try {
      const meRes = await fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${data.access_token}` },
      })
      if (meRes.ok) {
        const meData = await meRes.json()
        fullUser = meData.user
      }
    } catch (_) {}

    saveAuth(data.access_token, data.refresh_token, fullUser)
    return { ...data, user: fullUser }
  }, [saveAuth])

  const register = useCallback(async (username, email, password) => {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '注册失败' }))
      throw new Error(err.detail || '注册失败')
    }
    return await res.json()
  }, [])

  const logout = useCallback(async () => {
    try {
      if (token) {
        const saved = localStorage.getItem(AUTH_KEY)
        const refreshToken = saved ? JSON.parse(saved).refreshToken : null
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
    try {
      const res = await fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setUser(data.user)
        return true
      }
    } catch { /* 无需处理 */ }
    clearAuth()
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
    <AuthContext.Provider value={{ user, token, loading, isAdmin, permissions, roleName, hasPermission, login, register, logout, verifyToken, saveAuth, clearAuth }}>
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
