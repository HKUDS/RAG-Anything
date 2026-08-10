import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = (path) => readFileSync(resolve(process.cwd(), path), 'utf8')

test('default client has no public registration route, link, or request helper', () => {
  const app = source('src/App.jsx')
  const login = source('src/pages/LoginPage.jsx')
  const auth = source('src/context/AuthContext.jsx')
  assert.doesNotMatch(app, /RegisterPage|path="\/register"/)
  assert.doesNotMatch(login, /to="\/register"|立即注册/)
  assert.doesNotMatch(auth, /\/api\/auth\/register|const register/)
})

test('refresh bootstrap never restores a cached identity after /auth/me fails', () => {
  const auth = source('src/context/AuthContext.jsx')
  assert.doesNotMatch(auth, /fullUser = s \? JSON\.parse\(s\)\.user/)
  assert.match(auth, /removeStoredAuth\(\)/)
  assert.match(auth, /res\.status === 401 \|\| res\.status === 403/)
})

test('user-management requests clear a revoked administrator session', () => {
  const usersPage = source('src/pages/AdminUsersPage.jsx')
  const editModal = source('src/components/EditUserModal.jsx')
  assert.match(usersPage, /e\.status === 401[\s\S]{0,80}clearAuth\(\)/)
  assert.match(editModal, /response\.status === 401[\s\S]{0,80}clearAuth\(\)/)
})
