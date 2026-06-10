import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BookOpen, Loader2, ArrowRight } from 'lucide-react'
import { motion } from 'framer-motion'
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
          <p className="text-sm text-warm-500 mt-2">欢迎回来，继续你的知识探索 ✨</p>
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

            <div>
              <label className="block text-xs font-medium text-warm-600 mb-1.5">用户名</label>
              <input
                type="text"
                className="input-field text-sm py-2.5 w-full"
                placeholder="请输入用户名"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-warm-600 mb-1.5">密码</label>
              <input
                type="password"
                className="input-field text-sm py-2.5 w-full"
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
              {loading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <ArrowRight size={16} />
              )}
              {loading ? '正在登录…' : '登录'}
            </button>
          </form>

          <p className="text-center text-xs text-warm-500 mt-5">
            还没有账号？{' '}
            <Link to="/register" className="text-coral-500 hover:text-coral-600 font-medium transition-colors">
              立即注册
            </Link>
          </p>
        </div>

        <p className="text-center text-[11px] text-warm-500 mt-6">
          📚 让知识管理变得温暖有序
        </p>
      </motion.div>
    </div>
  )
}
