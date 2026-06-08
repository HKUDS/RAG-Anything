import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { UserPlus, Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!username.trim() || !email.trim() || !password) {
      setError('请填写所有字段')
      return
    }
    if (username.trim().length < 2) {
      setError('用户名至少 2 个字符')
      return
    }
    if (!email.includes('@')) {
      setError('请输入有效的邮箱地址')
      return
    }
    if (password.length < 6) {
      setError('密码至少需要 6 位')
      return
    }
    if (password !== confirmPw) {
      setError('两次密码不一致')
      return
    }

    setLoading(true)
    try {
      await register(username.trim(), email.trim(), password)
      setSuccess('注册成功！即将跳转到登录页…')
      setTimeout(() => navigate('/login'), 1500)
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
          <p className="text-xs text-slate-500 mt-2">创建新账号</p>
        </div>

        {/* Card */}
        <div className="glass p-6 rounded-xl">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                {error}
              </div>
            )}
            {success && (
              <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs">
                {success}
              </div>
            )}

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">用户名</label>
              <input
                type="text"
                className="input-field text-sm py-2 w-full"
                placeholder="至少 2 个字符"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">邮箱</label>
              <input
                type="email"
                className="input-field text-sm py-2 w-full"
                placeholder="your@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">密码</label>
              <input
                type="password"
                className="input-field text-sm py-2 w-full"
                placeholder="至少 6 位"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">确认密码</label>
              <input
                type="password"
                className="input-field text-sm py-2 w-full"
                placeholder="再次输入密码"
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full py-2.5 text-sm flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={16} />}
              {loading ? '注册中…' : '注册'}
            </button>
          </form>

          <p className="text-center text-xs text-slate-500 mt-4">
            已有账号？{' '}
            <Link to="/login" className="text-neon-400 hover:text-neon-300">
              立即登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
