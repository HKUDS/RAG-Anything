import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { UserPlus, Loader2, BookOpen } from 'lucide-react'
import { motion } from 'framer-motion'
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
    <div className="min-h-screen flex items-center justify-center bg-warm-100 px-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-sm"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-coral-500 shadow-warm-md mb-4">
            <BookOpen size={26} className="text-white" />
          </div>
          <h1 className="font-display font-semibold text-2xl tracking-tight text-warm-800">
            RAG<span className="text-coral-500">Anything</span>
          </h1>
          <p className="text-sm text-warm-500 mt-2">创建账号，开启知识管理之旅 🌱</p>
        </div>

        {/* Card */}
        <div className="card p-6 shadow-warm">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-600 text-xs"
              >
                {error}
              </motion.div>
            )}
            {success && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="p-3 rounded-xl bg-sage-50 border border-sage-200 text-sage-700 text-xs"
              >
                {success}
              </motion.div>
            )}

            <div>
              <label className="block text-xs font-medium text-warm-600 mb-1.5">用户名</label>
              <input
                type="text"
                className="input-field text-sm py-2.5 w-full"
                placeholder="至少 2 个字符"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-warm-600 mb-1.5">邮箱</label>
              <input
                type="email"
                className="input-field text-sm py-2.5 w-full"
                placeholder="your@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-warm-600 mb-1.5">密码</label>
              <input
                type="password"
                className="input-field text-sm py-2.5 w-full"
                placeholder="至少 6 位"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-warm-600 mb-1.5">确认密码</label>
              <input
                type="password"
                className="input-field text-sm py-2.5 w-full"
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

          <p className="text-center text-xs text-warm-500 mt-5">
            已有账号？{' '}
            <Link to="/login" className="text-coral-500 hover:text-coral-600 font-medium transition-colors">
              立即登录
            </Link>
          </p>
        </div>
      </motion.div>
    </div>
  )
}
