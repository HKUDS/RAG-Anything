import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Zap, Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('请填写用户名和密码')
      return
    }
    setLoading(true)
    try {
      await login(username.trim(), password)
      navigate('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <h1 className="font-display font-bold text-2xl tracking-tight">
            <span className="text-neon-400">RAG</span>
            <span className="text-slate-300">Anything</span>
          </h1>
          <p className="text-xs text-slate-500 mt-2">登录以访问知识库管理系统</p>
        </div>

        {/* Card */}
        <div className="glass p-6 rounded-xl">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                {error}
              </div>
            )}

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">用户名</label>
              <input
                type="text"
                className="input-field text-sm py-2 w-full"
                placeholder="请输入用户名"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">密码</label>
              <input
                type="password"
                className="input-field text-sm py-2 w-full"
                placeholder="请输入密码"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full py-2.5 text-sm flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />}
              {loading ? '登录中…' : '登录'}
            </button>
          </form>

          <p className="text-center text-xs text-slate-500 mt-4">
            还没有账号？{' '}
            <Link to="/register" className="text-neon-400 hover:text-neon-300">
              立即注册
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
