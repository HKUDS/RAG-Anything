import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { UserPlus, Loader2, BookOpen, Check, Circle } from 'lucide-react'
import { motion } from 'framer-motion'
import { useAuth } from '../context/AuthContext'

function checkPasswordStrength(pw) {
  return {
    length: pw.length >= 8,
    upper: /[A-Z]/.test(pw),
    lower: /[a-z]/.test(pw),
    digit: /[0-9]/.test(pw),
    special: /[^A-Za-z0-9]/.test(pw),
    score() {
      return [this.upper, this.lower, this.digit, this.special].filter(Boolean).length
    },
  }
}

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const [pwStrength, setPwStrength] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!username.trim() || !password) {
      setError('请填写所有字段')
      return
    }
    if (username.trim().length < 2) {
      setError('用户名至少 2 个字符')
      return
    }

    const strength = checkPasswordStrength(password)
    if (strength.score() < 3) {
      setError('密码需包含大写字母、小写字母、数字、特殊字符中的至少三类')
      return
    }
    if (password !== confirmPw) {
      setError('两次密码不一致')
      return
    }

    setLoading(true)
    try {
      await register(username.trim(), password)
      setSuccess('注册成功！即将跳转到登录页…')
      setTimeout(() => navigate('/login'), 1500)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const strength = password ? checkPasswordStrength(password) : null

  return (
    <div className="min-h-screen flex items-center justify-center bg-cloud-100 dark:bg-sky-950/40 px-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-sm"
      >
        {/* 标识 */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-sky-500 shadow-cloud-md mb-4">
            <BookOpen size={26} className="text-white" />
          </div>
          <h1 className="font-display font-semibold text-2xl tracking-tight text-ink-primary dark:text-cloud-200">
            知元
          </h1>
          <p className="text-sm text-ink-muted dark:text-cloud-500 mt-2">创建账号，开始使用多模态教学知识服务平台</p>
        </div>

        {/* 卡片 */}
        <div className="card p-6 shadow-cloud dark:bg-sky-900/30 dark:border-sky-800/30">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="p-3 rounded-xl bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800/30 text-rose-600 dark:text-rose-400 text-xs"
              >
                {error}
              </motion.div>
            )}
            {success && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="p-3 rounded-xl bg-sage-50 dark:bg-sage-900/20 border border-sage-200 dark:border-sage-800/30 text-sage-700 dark:text-sage-400 text-xs"
              >
                {success}
              </motion.div>
            )}

            <div>
              <label className="block text-xs font-medium text-ink-body dark:text-cloud-300 mb-1.5">用户名</label>
              <input
                type="text"
                className="input-field text-sm py-2.5 w-full"
                placeholder="至少 2 个字符"
                value={username}
                onChange={e => setUsername(e.target.value)}
                maxLength={64}
                required
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-body dark:text-cloud-300 mb-1.5">密码</label>
              <input
                type="password"
                className="input-field text-sm py-2.5 w-full"
                placeholder="至少 8 位，含大小写字母、数字、特殊字符中的 3 类"
                value={password}
                onChange={e => { setPassword(e.target.value); setPwStrength(checkPasswordStrength(e.target.value)) }}
              />
              {strength && (
                <div className="mt-2 space-y-1">
                  {[
                    ['length', '至少 8 位'],
                    ['upper', '大写字母'],
                    ['lower', '小写字母'],
                    ['digit', '数字'],
                    ['special', '特殊字符'],
                  ].map(([k, label]) => (
                    <div key={k} className={`flex items-center gap-1.5 text-xs ${strength[k] ? 'text-sage-600 dark:text-sage-400' : 'text-ink-muted dark:text-cloud-500'}`}>
                      {strength[k] ? <Check size={11} /> : <Circle size={11} />} {label}
                    </div>
                  ))}
                  <div className="text-xs text-ink-muted dark:text-cloud-500 mt-1">满足 {strength.score()} / 4 类</div>
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-body dark:text-cloud-300 mb-1.5">确认密码</label>
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

          <p className="text-center text-xs text-ink-muted dark:text-cloud-500 mt-5">
            已有账号？{' '}
            <Link to="/login" className="text-sky-500 dark:text-sky-400 hover:text-sky-600 dark:hover:text-sky-300 font-medium transition-colors">
              立即登录
            </Link>
          </p>
        </div>

        <p className="text-center text-2xs text-ink-muted dark:text-cloud-500 mt-6">
          知元 · 多模态教学知识服务平台
        </p>
      </motion.div>
    </div>
  )
}
