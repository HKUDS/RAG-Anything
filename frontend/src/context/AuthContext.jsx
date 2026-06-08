import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const AuthContext = createContext(null)

const AUTH_KEY = 'raganything_auth'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)

  // 从 localStorage 恢复登录状态
  useEffect(() => {
    try {
      const saved = localStorage.getItem(AUTH_KEY)
      if (saved) {
        const data = JSON.parse(saved)
        setToken(data.token)
        setUser(data.user)
      }
    } catch {} finally {
      setLoading(false)
    }
  }, [])

  const saveAuth = useCallback((t, u) => {
    setToken(t)
    setUser(u)
    localStorage.setItem(AUTH_KEY, JSON.stringify({ token: t, user: u }))
  }, [])

  const clearAuth = useCallback(() => {
    setToken(null)
    setUser(null)
    localStorage.removeItem(AUTH_KEY)
  }, [])

  const login = useCallback(async (username, password) => {
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
    saveAuth(data.token, data.user)
    return data
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
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        })
      }
    } catch {} finally {
      clearAuth()
    }
  }, [token, clearAuth])

  // 验证 Token 是否仍然有效
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
    } catch {}
    clearAuth()
    return false
  }, [token, clearAuth])

  const isAdmin = user?.is_admin === true || user?.is_admin === 1

  return (
    <AuthContext.Provider value={{ user, token, loading, isAdmin, login, register, logout, verifyToken, saveAuth, clearAuth }}>
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
