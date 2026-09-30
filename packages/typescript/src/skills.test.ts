import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { test } from 'node:test'

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { ResultSchema } from '@modelcontextprotocol/sdk/types.js'

import { skills, SKILLS_EXTENSION } from './skills.js'

function skillsDir(files: Record<string, string | Buffer>): string {
  const root = mkdtempSync(join(tmpdir(), 'skills-'))
  for (const [path, body] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true })
    writeFileSync(join(root, path), body)
  }
  return root
}

async function connect(dir: string): Promise<Client> {
  const server = new McpServer({ name: 't', version: '0' })
  skills(server, dir)
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair()
  await server.connect(serverSide)
  const client = new Client({ name: 't', version: '0' })
  await client.connect(clientSide)
  return client
}

const Loose = ResultSchema.loose()

async function call(client: Client, method: string, params: Record<string, unknown> = {}) {
  return (await client.request({ method, params }, Loose)) as Record<string, any>
}

test('lists every file with a digest and size the served bytes match', async () => {
  const dir = skillsDir({
    'weekly-review/SKILL.md':
      '---\nname: weekly-review\ndescription: Review the week.\nmetadata:\n  version: 1\n---\n\n# Weekly review\n',
    'weekly-review/references/checklist.md': '# Checklist\n',
    'weekly-review/assets/logo.bin': Buffer.from([0xff, 0xfe, 0x00, 0x01]),
  })
  const client = await connect(dir)

  assert.ok(SKILLS_EXTENSION in (client.getServerCapabilities()?.extensions ?? {}))

  const { skills: listed, resultType, ttlMs, cacheScope } = await call(client, 'skills/list')
  assert.equal(resultType, 'complete')
  assert.equal(typeof ttlMs, 'number')
  assert.equal(cacheScope, 'public')

  const [entry] = listed
  assert.equal(entry.uri, 'skill://weekly-review/SKILL.md')
  // Typed, not stringified: a host compares these against its own YAML parse.
  assert.deepEqual(entry.frontmatter.metadata, { version: 1 })
  assert.deepEqual(
    entry.resources.map((r: { uri: string }) => r.uri),
    [
      'skill://weekly-review/SKILL.md',
      'skill://weekly-review/assets/logo.bin',
      'skill://weekly-review/references/checklist.md',
    ],
  )

  for (const file of entry.resources) {
    const { contents } = await client.readResource({ uri: file.uri })
    const [content] = contents
    const bytes =
      'text' in content ? Buffer.from(content.text as string, 'utf8') : Buffer.from(content.blob as string, 'base64')
    assert.equal(`sha256:${createHash('sha256').update(bytes).digest('hex')}`, file.digest, file.uri)
    assert.equal(bytes.length, file.size, file.uri)
  }
})

test('get returns the listed entry and rejects an unknown uri with -32602', async () => {
  const client = await connect(skillsDir({ 'a/SKILL.md': '---\nname: a\ndescription: A.\n---\n' }))

  const { skills: [listed] } = await call(client, 'skills/list')
  const { skill } = await call(client, 'skills/get', { uri: 'skill://a/SKILL.md' })
  assert.deepEqual(skill, listed)

  await assert.rejects(call(client, 'skills/get', { uri: 'skill://nope/SKILL.md' }), { code: -32602 })
})

test('a name that is not its directory fails at startup', () => {
  const dir = skillsDir({ 'a/SKILL.md': '---\nname: b\ndescription: A.\n---\n' })
  assert.throws(() => skills(new McpServer({ name: 't', version: '0' }), dir), /must match its directory/)
})

test('no skills fails at startup', () => {
  const dir = skillsDir({ 'README.md': 'nothing here' })
  assert.throws(() => skills(new McpServer({ name: 't', version: '0' }), dir), /no <name>\/SKILL.md/)
})
