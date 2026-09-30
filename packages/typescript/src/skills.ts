import { isUtf8 } from 'node:buffer'
import { createHash } from 'node:crypto'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { extname, join, relative, resolve, sep } from 'node:path'

import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { McpError, ErrorCode, RequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { parse } from 'yaml'
import { z } from 'zod'

export const SKILLS_EXTENSION = 'io.modelcontextprotocol/skills'

// Manifests are computed once from the files on disk, so an entry stays valid
// for as long as the process does. Five minutes is the spec's own example;
// nothing here is per-user, hence public.
const CACHE = { ttlMs: 300_000, cacheScope: 'public' } as const

interface SkillFile {
  uri: string
  digest: string
  size: number
  bytes: Buffer
}

export interface SkillEntry {
  uri: string
  frontmatter: Record<string, unknown>
  resources: { uri: string; digest: string; size: number }[]
}

interface Skill {
  entry: SkillEntry
  files: SkillFile[]
}

const ListSkillsSchema = RequestSchema.extend({ method: z.literal('skills/list') })
const GetSkillSchema = RequestSchema.extend({
  method: z.literal('skills/get'),
  params: z.looseObject({ uri: z.string() }),
})

// A stateless server builds a fresh McpServer per request, so the scan (and
// every digest) is done once per directory rather than on every call.
const scanned = new Map<string, Skill[]>()

/** Serve every `<dir>/<name>/SKILL.md` as an MCP skill (SEP-2640): the
 *  `io.modelcontextprotocol/skills` capability, `skills/list` and `skills/get`
 *  with a SHA-256 manifest per skill, and each file over `resources/read` at
 *  `skill://<name>/<path>`. Call before `connect`. Throws rather than serving a
 *  skill a host would reject. */
export function skills(server: McpServer, dir = 'skills'): void {
  const root = resolve(dir)
  let found = scanned.get(root)
  if (!found) {
    found = scan(root)
    scanned.set(root, found)
  }
  const byUri = new Map(found.map((skill) => [skill.entry.uri, skill.entry]))
  const listing = found.map((skill) => skill.entry)

  server.server.registerCapabilities({ resources: {}, extensions: { [SKILLS_EXTENSION]: {} } })
  // ponytail: one page, every skill. Fine at a handful; add a cursor when a
  // server ships enough that one response gets heavy.
  server.server.setRequestHandler(ListSkillsSchema, () => ({
    resultType: 'complete',
    skills: listing,
    ...CACHE,
  }))
  server.server.setRequestHandler(GetSkillSchema, (request) => {
    const entry = byUri.get(request.params.uri)
    if (!entry) throw new McpError(ErrorCode.InvalidParams, `Unknown skill: ${request.params.uri}`)
    return { resultType: 'complete', skill: entry, ...CACHE }
  })

  for (const skill of found) {
    for (const file of skill.files) {
      server.registerResource(file.uri, file.uri, { mimeType: mimeType(file) }, () => ({
        contents: [content(file)],
      }))
    }
  }
}

function scan(root: string): Skill[] {
  let names: string[]
  try {
    names = readdirSync(root).sort()
  } catch {
    throw new Error(`skills: no skills directory at ${root}`)
  }
  const found = names
    .filter((name) => statSync(join(root, name)).isDirectory())
    .filter((name) => statSync(join(root, name, 'SKILL.md'), { throwIfNoEntry: false })?.isFile())
    .map((name) => load(join(root, name), name))
  if (found.length === 0) throw new Error(`skills: no <name>/SKILL.md under ${root}`)
  return found
}

function load(dir: string, name: string): Skill {
  const main = join(dir, 'SKILL.md')
  const frontmatter = parseFrontmatter(readFileSync(main, 'utf8'))
  if (!frontmatter?.description) {
    throw new Error(`skills: ${main} needs frontmatter with a name and a description`)
  }
  if (frontmatter.name !== name) {
    throw new Error(
      `skills: ${main} is named ${JSON.stringify(frontmatter.name)}; ` +
        `a skill's name must match its directory, ${JSON.stringify(name)}`,
    )
  }
  // SKILL.md first, as the spec's examples list it.
  const paths = [main, ...walk(dir).filter((path) => path !== main).sort()]
  const files = paths.map((path): SkillFile => {
    const bytes = readFileSync(path)
    return {
      uri: `skill://${name}/${relative(dir, path).split(sep).join('/')}`,
      digest: `sha256:${createHash('sha256').update(bytes).digest('hex')}`,
      size: bytes.length,
      bytes,
    }
  })
  return {
    entry: {
      uri: `skill://${name}/SKILL.md`,
      frontmatter,
      resources: files.map(({ uri, digest, size }) => ({ uri, digest, size })),
    },
    files,
  }
}

function parseFrontmatter(text: string): Record<string, unknown> | undefined {
  const match = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(text)
  const parsed: unknown = match ? parse(match[1]) : undefined
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : undefined
}

// Regular files only: a symlink could point outside the skill, and serving it
// would publish whatever it points at.
function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return walk(path)
    return entry.isFile() ? [path] : []
  })
}

function mimeType(file: SkillFile): string {
  if (!isUtf8(file.bytes)) return 'application/octet-stream'
  return extname(file.uri) === '.md' ? 'text/markdown' : 'text/plain'
}

function content(file: SkillFile) {
  // Text only when it round-trips: a host checks the digest against the bytes
  // it reassembles, and a lossy decode would fail that check.
  return isUtf8(file.bytes)
    ? { uri: file.uri, mimeType: mimeType(file), text: file.bytes.toString('utf8') }
    : { uri: file.uri, mimeType: mimeType(file), blob: file.bytes.toString('base64') }
}

