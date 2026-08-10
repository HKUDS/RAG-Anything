import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'

const pagesDir = new URL('../pages/', import.meta.url)
const source = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

const setCurrentKBImport = /import\s*\{[^}]*\bsetCurrentKB\b[^}]*\}\s*from\s*['"]\.\.\/utils\/api['"]/

test('every page calling setCurrentKB imports it from ../utils/api', () => {
  const pageFiles = readdirSync(pagesDir).filter(name => name.endsWith('.jsx'))
  assert.ok(pageFiles.length > 0, 'expected .jsx pages under src/pages to scan')

  for (const name of pageFiles) {
    const pageSource = source(`../pages/${name}`)
    if (!pageSource.includes('setCurrentKB(')) continue
    assert.match(
      pageSource,
      setCurrentKBImport,
      `${name} calls setCurrentKB() but does not import it from '../utils/api'`
    )
  }
})
