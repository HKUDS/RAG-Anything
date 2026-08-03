import assert from 'node:assert/strict'
import { readFile, stat } from 'node:fs/promises'
import test from 'node:test'

const sourceRoot = new URL('./', import.meta.url)

test('shipped code parser uses the autorepair route and the legacy upload page is absent', async () => {
  const editor = await readFile(new URL('../components/GCodeEditor.jsx', sourceRoot), 'utf8')
  const page = await readFile(new URL('../pages/AutoRepairAgentPage.jsx', sourceRoot), 'utf8')

  assert.match(editor, /\/autorepair\/code\/parse/)
  assert.doesNotMatch(editor, /\/manufacturing\/code\/parse/)
  assert.doesNotMatch(page, /codeInput|codeLang|handleCodeParse|codeCopied/)
  await assert.rejects(
    stat(new URL('../pages/UploadPage.jsx', sourceRoot)),
    error => error?.code === 'ENOENT',
  )
})
