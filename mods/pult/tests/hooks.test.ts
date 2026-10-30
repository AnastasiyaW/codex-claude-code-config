import { expect, mock, test } from 'claude-code/testing'
import type { RenderElement } from 'claude-code'

const MSG = [{ role: 'user' as const, text: 'привет', toolUses: [] }]
const PANE = {
  component: 'Pane',
  requestId: 'pult-activity',
  props: { title: 'Активность', isFocused: false, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const
const usage = { input_tokens: 1, output_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }
// On Windows the engine returns paths with backslashes.
const slash = (p: string) => p.replace(/\\/g, '/')
// A disk where every path exists at its own spelling, except: `links` (path -> target, followed for
// everything below it; target '' is a link that leads nowhere, stat answers isLink without realPath)
// and `missing` (paths absent with everything below them; stat rejects).
// `unreported` redirects like a link but never says so (a Windows junction listed as a folder).
function plainDisk(on: Parameters<Parameters<typeof test>[1]>[1], links: Record<string, string> = {}, missing: string[] = [],
  unreported: Record<string, string> = {}) {
  const below = (p: string, top: string) => p === top || p.startsWith(`${top}/`)
  on('fs.stat', async ($, e) => {
    const p = slash(String((e as { path: string }).path))
    const hidden = Object.keys(unreported).find(from => below(p, from))
    if (hidden !== undefined) {
      return { value: { kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false, realPath: unreported[hidden]! + p.slice(hidden.length) } }
    }
    const link = Object.keys(links).find(from => below(p, from))
    if (link !== undefined && links[link] === '') {
      if (p !== link) throw new Error('ENOENT')
      return { value: { kind: 'other' as const, size: 0, mtimeMs: 0, isLink: true } }
    }
    const realPath = link === undefined ? p : links[link]! + p.slice(link.length)
    if (missing.some(m => below(p, m) || below(realPath, m))) throw new Error('ENOENT')
    return { value: { kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: p in links, realPath } }
  })
}
const listing = (names: string[], links: string[] = []) =>
  names.map(name => ({ name, kind: 'file' as const, size: 0, mtimeMs: 0, isLink: links.includes(name) }))

test('Activity pane: running call, permission prompt, result', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  let release: () => void = () => undefined
  const gate = new Promise<void>(r => (release = r))
  on('tool.call', { tool: 'Bash' }, async () => {
    await gate
    return { result: { stdout: 'ok', stderr: '', interrupted: false } }
  })
  on('classic.PermissionRequest', async () => ({}))

  const call = $.tool.call({ tool: 'Bash', tool_use_id: 'tu1', command: 'git status', description: 'Show working tree status' })
  await clock.settle()
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'pult', surface, ...PANE })
    expect(await ui.find({ type: 'Text', text: /▶ Bash .*Show working tree status/ })).toBeDefined()
    await ui.unmount()
  }

  await $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: { command: 'git status' } })
  const asked = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...PANE })
  expect(await asked.find({ type: 'Text', text: /⏸ запрошено подтверждение Bash/ })).toBeDefined()
  await asked.unmount()

  release()
  await call
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'pult', surface, ...PANE })
    expect(await ui.find({ type: 'Text', text: /✓ Bash .*Show working tree status/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'ничего не выполняется' })).toBeDefined()
    await ui.unmount()
  }
})

test('TodoWrite plan appears on the pane', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  on('tool.call', { tool: 'TodoWrite' }, async () => ({ result: { oldTodos: [], newTodos: [] } }))
  await $.tool.call({
    tool: 'TodoWrite',
    todos: [
      { content: 'Собрать мод', status: 'completed', activeForm: 'Собираю мод' },
      { content: 'Проверить тесты', status: 'in_progress', activeForm: 'Проверяю тесты' },
    ],
  })
  const ui = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: '✓ Собрать мод' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '▶ Проверить тесты' })).toBeDefined()
  await ui.unmount()
})

test('before compaction a handoff and an INDEX.md line are written', async ($, on) => {
  mock.clock(on, { now: new Date(2026, 9, 13, 9, 5).getTime() })
  const written: Record<string, string> = {}
  on('session.root', async () => ({ value: 'D:/My_Project' }))
  on('session.id', async () => ({ value: '7f5720a1-b99b-485c-beb3-085137ba8390' }))
  on('session.turns', async () => ({ value: 5 }))
  plainDisk(on)
  on('fs.list', async () => ({ value: [] }))
  on('fs.exists', async ($, e) => ({ value: slash(String((e as { path: string }).path)) in written }))
  on('fs.read', async ($, e) => {
    const p = slash(String((e as { path: string }).path))
    if (p in written) return { value: written[p]! }
    throw new Error('ENOENT')
  })
  on('fs.write', async ($, e) => {
    const { path, text } = e as { path: string; text: string }
    written[slash(path)] = text
    return { value: undefined }
  })
  on('model.fork', async () => ({ value: { isAnswered: true as const, text: '# Handoff: тест\n\n## Next step\nПродолжить.', usage } }))
  on('session.compact', async () => ({ messages: MSG }))

  await $.session.compact({ trigger: 'manual', messages: MSG })

  expect(Object.keys(written).sort()).toEqual([
    'D:/My_Project/.claude/handoffs/INDEX.md',
    'D:/My_Project/.claude/handoffs/my-project/2026-10-13_09-05_7f5720a1.md',
  ])
  expect(written['D:/My_Project/.claude/handoffs/my-project/2026-10-13_09-05_7f5720a1.md']).toContain('## Next step')
  expect(written['D:/My_Project/.claude/handoffs/INDEX.md']).toContain('| 7f5720a1 | my-project | хендофф модом pult: перед /compact |')
})

// One compaction on project `root`; returns the paths the mod wrote.
async function compactWith($: Parameters<Parameters<typeof test>[1]>[0], on: Parameters<Parameters<typeof test>[1]>[1],
  root: string, disk: () => void, list: (dir: string) => ReturnType<typeof listing> = () => [], existing: string[] = []) {
  mock.clock(on, { now: new Date(2026, 9, 13, 9, 5).getTime() })
  const written: string[] = []
  on('session.root', async () => ({ value: root }))
  on('session.id', async () => ({ value: 'abcdef12-0000' }))
  on('session.turns', async () => ({ value: 5 }))
  disk()
  on('fs.list', async ($, e) => ({ value: list(slash(String((e as { path: string }).path))) }))
  on('fs.exists', async ($, e) => ({ value: existing.includes(slash(String((e as { path: string }).path))) }))
  on('fs.write', async ($, e) => {
    written.push(slash((e as { path: string }).path))
    return { value: undefined }
  })
  on('model.fork', async () => ({ value: { isAnswered: true as const, text: '# Handoff', usage } }))
  on('session.compact', async () => ({ messages: MSG }))
  await $.session.compact({ trigger: 'manual', messages: MSG })
  return written
}
const HANDOFF = 'D:/p/.claude/handoffs/p/2026-10-13_09-05_abcdef12.md'

test('a handoffs folder linked outside the project gets nothing (the file does not exist yet)', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () =>
    plainDisk(on, { 'D:/p/.claude/handoffs': 'E:/outside' }, ['E:/outside/p']))
  expect(written).toEqual([])
})

test('a handoff file that is a link elsewhere gets nothing', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, { [HANDOFF]: 'E:/outside/target.txt' }))
  expect(written).toEqual([])
})

test('a dangling INDEX.md link is not followed, the handoff is still written', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, {}, ['D:/p/.claude/handoffs/INDEX.md']),
    dir => (dir === 'D:/p/.claude/handoffs' ? listing(['INDEX.md'], ['INDEX.md']) : []))
  expect(written).toEqual([HANDOFF])
})

test('a link to a sibling folder with the same prefix is outside', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () =>
    plainDisk(on, { 'D:/p/.claude/handoffs': 'D:/p2/handoffs' }, ['D:/p2/handoffs/p']))
  expect(written).toEqual([])
})

test('a redirect the disk does not report as a link is still caught by where it lands', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () =>
    plainDisk(on, {}, [], { 'D:/p/.claude/handoffs': 'D:/p2/handoffs' }))
  expect(written).toEqual([])
})

test('a handoffs folder linked into .claude/rules (inside the project) gets nothing', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, { 'D:/p/.claude/handoffs': 'D:/p/.claude/rules' }),
    dir => (dir === 'D:/p/.claude' ? listing(['handoffs', 'rules'], ['handoffs']) : []))
  expect(written).toEqual([])
})

test('a .claude folder that is a link above an existing handoffs folder gets nothing', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, { 'D:/p/.claude': 'D:/p/docs' }),
    dir => (dir === 'D:/p' ? listing(['.claude', 'docs'], ['.claude']) : []))
  expect(written).toEqual([])
})

test('an INDEX.md linked to a git hook inside the project is not written through', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () =>
    plainDisk(on, { 'D:/p/.claude/handoffs/INDEX.md': 'D:/p/.git/hooks/pre-commit' }))
  expect(written).toEqual([HANDOFF])
})

test('a dangling link that stat reports (isLink, no realPath) is not followed', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, { 'D:/p/.claude/handoffs/INDEX.md': '' }))
  expect(written).toEqual([HANDOFF])
})

test('a dangling link differing only in case is caught on a case-sensitive root', async ($, on) => {
  const written = await compactWith($, on, '//srv/share/p', () => plainDisk(on, {}, ['//srv/share/p/.claude/handoffs/INDEX.md']),
    dir => (dir === '//srv/share/p/.claude/handoffs' ? listing(['index.md'], ['index.md']) : []))
  expect(written).toEqual(['//srv/share/p/.claude/handoffs/p/2026-10-13_09-05_abcdef12.md'])
})

test('a dangling link at the project folder level gets nothing', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, {}, ['D:/p/.claude/handoffs/p']),
    dir => (dir === 'D:/p/.claude/handoffs' ? listing(['p'], ['p']) : []))
  expect(written).toEqual([])
})

test('a folder that exists but cannot be listed gets nothing', async ($, on) => {
  const written = await compactWith($, on, 'D:/p', () => plainDisk(on, {}, [HANDOFF]),
    dir => {
      if (dir === 'D:/p/.claude/handoffs/p') throw new Error('EACCES')
      return []
    }, ['D:/p/.claude/handoffs/p'])
  expect(written).toEqual([])
})

test('drive letter case does not matter on Windows', async ($, on) => {
  const written = await compactWith($, on, 'd:/p', () => plainDisk(on, { 'd:/p': 'D:/P' }, ['D:/P/.claude', 'd:/p/.claude']))
  expect(written).toEqual(['d:/p/.claude/handoffs/p/2026-10-13_09-05_abcdef12.md', 'd:/p/.claude/handoffs/INDEX.md'])
})

test('a fresh handoff is not rewritten', async ($, on) => {
  const clock = mock.clock(on, { now: 5_000_000 })
  let forks = 0
  on('session.root', async () => ({ value: 'D:/p' }))
  on('session.turns', async () => ({ value: 5 }))
  on('session.id', async () => ({ value: 'abcdef12-0000' }))
  on('fs.list', async () => ({ value: [{ name: '2026-10-13_09-00_abcdef12.md', kind: 'file' as const, size: 10, mtimeMs: clock.now() - 60_000, isLink: false }] }))
  on('model.fork', async () => {
    forks++
    return { value: { isAnswered: false as const, reason: 'empty-reply' as const, usage } }
  })
  on('session.compact', async () => ({ messages: MSG }))
  await $.session.compact({ trigger: 'auto', messages: MSG })
  expect(forks).toBe(0)
})

test('a locked INDEX.md is not wiped, the handoff is still written', async ($, on) => {
  mock.clock(on, { now: new Date(2026, 9, 13, 9, 5).getTime() })
  const written: Record<string, string> = {}
  on('session.root', async () => ({ value: 'D:/p' }))
  on('session.id', async () => ({ value: 'abcdef12-0000' }))
  on('session.turns', async () => ({ value: 5 }))
  plainDisk(on)
  on('fs.list', async () => ({ value: [] }))
  on('fs.exists', async ($, e) => ({ value: slash(String((e as { path: string }).path)).endsWith('INDEX.md') }))
  on('fs.read', async () => {
    throw new Error('EBUSY')
  })
  on('fs.write', async ($, e) => {
    const { path, text } = e as { path: string; text: string }
    written[slash(path)] = text
    return { value: undefined }
  })
  on('model.fork', async () => ({ value: { isAnswered: true as const, text: '# Handoff', usage } }))
  on('session.compact', async () => ({ messages: MSG }))
  await $.session.compact({ trigger: 'manual', messages: MSG })
  expect(Object.keys(written)).toEqual(['D:/p/.claude/handoffs/p/2026-10-13_09-05_abcdef12.md'])
})

test('the model did not answer: a draft from the last messages is written', async ($, on) => {
  mock.clock(on, { now: new Date(2026, 9, 13, 9, 5).getTime() })
  const written: Record<string, string> = {}
  on('session.root', async () => ({ value: 'D:/p' }))
  on('session.id', async () => ({ value: 'abcdef12-0000' }))
  on('session.turns', async () => ({ value: 5 }))
  plainDisk(on)
  on('fs.list', async () => ({ value: [] }))
  on('fs.exists', async () => ({ value: false }))
  on('fs.write', async ($, e) => {
    const { path, text } = e as { path: string; text: string }
    written[slash(path)] = text
    return { value: undefined }
  })
  on('model.fork', async () => ({ value: { isAnswered: false as const, reason: 'api-error' as const, status: 400, error: 'invalid_request' as const, usage } }))
  on('session.compact', async () => ({ messages: MSG }))
  await $.session.compact({ trigger: 'auto', messages: MSG })
  const draft = written['D:/p/.claude/handoffs/p/2026-10-13_09-05_abcdef12.md']
  expect(draft).toContain('черновик без модели: api-error')
  expect(draft).toContain('- привет')
  expect(written['D:/p/.claude/handoffs/INDEX.md']).toContain('перед автосжатием')
})

test("a parallel session's handoff does not block this one", async ($, on) => {
  const clock = mock.clock(on, { now: 5_000_000 })
  let forks = 0
  on('session.root', async () => ({ value: 'D:/p' }))
  on('session.id', async () => ({ value: 'abcdef12-0000' }))
  on('session.turns', async () => ({ value: 5 }))
  on('fs.list', async () => ({ value: [{ name: '2026-10-13_09-00_99999999.md', kind: 'file' as const, size: 10, mtimeMs: clock.now() - 60_000, isLink: false }] }))
  on('fs.exists', async () => ({ value: false }))
  on('fs.write', async () => ({ value: undefined }))
  on('model.fork', async () => {
    forks++
    return { value: { isAnswered: true as const, text: '# Handoff', usage } }
  })
  on('session.compact', async () => ({ messages: MSG }))
  await $.session.compact({ trigger: 'auto', messages: MSG })
  expect(forks).toBe(1)
})

test("the user's own hook decided: the call is not marked as asked", async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  let release: () => void = () => undefined
  const gate = new Promise<void>(r => (release = r))
  on('tool.call', { tool: 'Bash' }, async () => {
    await gate
    return { result: { stdout: 'ok', stderr: '', interrupted: false } }
  })
  on('classic.PermissionRequest', async () => ({ decision: { behavior: 'allow' as const } }))
  const call = $.tool.call({ tool: 'Bash', tool_use_id: 'tu2', command: 'ls', description: 'List files' })
  await clock.settle()
  await $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: { command: 'ls' } })
  const ui = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: /▶ Bash .*List files/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /запрошено подтверждение/ })).toBeUndefined()
  await ui.unmount()
  release()
  await call
})

test('model progress is drawn above the prompt; when done, a check mark without "now"', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const BAND = {
    component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: true, maxRows: 10, bodyColumns: 100, scroll: { offset: 0, bodyRows: 10 }, view: {} },
  } as const
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => h($.ui.resolve(e).Box, {}) as RenderElement)
  const said = await $.tool.call({
    tool: 'mcp__pult__progress',
    title: 'Сборка датасета',
    done: 5,
    total: 12,
    now: 'разметка файлов',
    next: 'проверка',
    sub: { label: 'Transcribe', done: 17639, total: 29676 },
    counts: [{ label: 'доделано', n: 9 }],
  })
  expect(JSON.stringify(said)).toContain('Сборка датасета 5/12')
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'pult', surface, ...BAND })
    expect(await ui.find({ type: 'Text', text: 'Сборка датасета' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: ' 5/12 этапов' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'доделано 9' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'сейчас: разметка файлов' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Transcribe/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /59%/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'дальше: проверка' })).toBeDefined()
    await ui.unmount()
  }
  await $.tool.call({ tool: 'mcp__pult__progress', done: 12 })
  const ui = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: '✓ Сборка датасета ' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /сейчас:/ })).toBeUndefined()
  await ui.unmount()
  await $.tool.call({ tool: 'mcp__pult__progress', clear: true })
  const gone = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...BAND })
  expect(await gone.find({ type: 'Text', text: /датасета/ })).toBeUndefined()
  await gone.unmount()
})

test('the band shows a running call and empties after it ends', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  const BAND = {
    component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: true, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {} },
  } as const
  let release: () => void = () => undefined
  const gate = new Promise<void>(r => (release = r))
  on('tool.call', { tool: 'Bash' }, async () => {
    await gate
    return { result: { stdout: 'ok', stderr: '', interrupted: false } }
  })
  // Underneath the mod: the engine's empty band, drawn when the mod has nothing to show.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => h($.ui.resolve(e).Box, {}) as RenderElement)
  const call = $.tool.call({ tool: 'Bash', tool_use_id: 'tu3', command: 'npm test', description: 'Run tests' })
  await clock.settle()
  // Hidden for the first 3 seconds: short calls do not flicker the band.
  const early = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...BAND })
  expect(await early.find({ type: 'Text', text: /Run tests/ })).toBeUndefined()
  await early.unmount()
  await clock.advance(4000)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'pult', surface, ...BAND })
    expect(await ui.find({ type: 'Text', text: /▶ Bash .*Run tests/ })).toBeDefined()
    await ui.unmount()
  }
  release()
  await call
  const ui = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /Run tests/ })).toBeUndefined()
  await ui.unmount()
})

test('the model has not answered yet: /save-handoff writes nothing', async ($, on) => {
  mock.clock(on, { now: 5_000_000 })
  const written: string[] = []
  on('session.root', async () => ({ value: 'D:/p' }))
  on('session.id', async () => ({ value: 'abcdef12-0000' }))
  on('session.turns', async () => ({ value: 1 }))
  plainDisk(on)
  on('fs.list', async () => ({ value: [] }))
  on('fs.exists', async () => ({ value: false }))
  on('fs.write', async ($, e) => {
    written.push((e as { path: string }).path)
    return { value: undefined }
  })
  on('model.fork', async () => ({ value: { isAnswered: false as const, reason: 'nothing-to-fork' as const } }))
  const out = await $.command.run({
    command: 'save-handoff',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 80 },
  })
  expect(written).toEqual([])
  expect(JSON.stringify(out)).toContain('Писать нечего')
})

test('the fourth call of a turn without progress carries a hint, the fifth does not', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  on('tool.call', { tool: 'Read' }, async () => ({ result: { type: 'text', file: { filePath: 'a', content: '', numLines: 0, startLine: 1, totalLines: 0 } } }) as never)
  const results = []
  for (let i = 0; i < 5; i++) results.push(await $.tool.call({ tool: 'Read', file_path: 'a' }))
  const has = results.map(r => JSON.stringify(r).includes('mcp__pult__progress'))
  expect(has).toEqual([false, false, false, true, false])
})

test('the pane shows subagent model and context from its response', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const row = { id: 'a1', type: 'Explore', description: 'поиск', status: 'running' as const }
  on('agent.list', async () => ({ value: [row] }))
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn' as const, usage: { input_tokens: 10, output_tokens: 200, cache_read_input_tokens: 80_000, cache_creation_input_tokens: 4_000, model: 'claude-opus-5-5' } }
  })
  on('tool.call', { tool: 'Agent' }, async () => ({ result: {} }) as never)
  for await (const _ of $.turn.step({ turnId: 't1', index: 0, model: 'opus', messageCount: 1, agentId: 'a1' } as never)) void _
  await $.tool.call({ tool: 'Agent', tool_use_id: 'tu1', description: 'поиск', prompt: 'x' } as never)
  const ui = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: /Explore · поиск · opus 84k · расход 17k/ })).toBeDefined()
  await ui.unmount()
})

test("the agent's model is visible before its first response", async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  const row = { id: 'a1', type: 'Explore', description: 'поиск', status: 'running' as const }
  on('agent.list', async () => ({ value: [row] }))
  on('turn.step', async function* (_$, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: null, usage: null }
  })
  on('tool.call', { tool: 'Agent' }, async () => ({ result: {} }) as never)
  for await (const _ of $.turn.step({ turnId: 't1', index: 0, model: 'claude-sonnet-5-5', messageCount: 1, agentId: 'a1' } as never)) void _
  await $.tool.call({ tool: 'Agent', tool_use_id: 'tu1', description: 'поиск', prompt: 'x' } as never)
  const ui = await $.ui.mount({ plugin: 'pult', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: /Explore · поиск · sonnet$/ })).toBeDefined()
  await ui.unmount()
})

test('the model is asked once to suggest a new chat', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  on('session.measure', async (_$, e) => ({ changed: e.changed }))
  on('tool.call', { tool: 'Read' }, async () => ({ result: {} }) as never)
  const read = (id: string) => $.tool.call({ tool: 'Read', tool_use_id: id, file_path: 'x' } as never) as Promise<{ context?: string[] }>
  expect((await read('tu0')).context ?? []).toEqual([])
  await $.session.measure({ context: { tokens: 360_000, window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] })
  expect((await read('tu1')).context?.join(' ')).toContain('/compact')
  expect((await read('tu2')).context ?? []).toEqual([])
})

test('account limits from session.measure reach the status line', async ($, on) => {
  mock.clock(on, { now: Date.UTC(2026, 9, 15, 14, 0) })
  const statuses: (string | undefined)[] = []
  on('ui.status', async (_$, e) => {
    statuses.push((e as { text?: string }).text)
    return { value: undefined }
  })
  on('session.measure', async () => ({ changed: ['rateLimits' as const] }))
  await $.session.measure({ context: { window: 1_000_000 }, rateLimits: [{ kind: 'five_hour', percentUsed: 57 }, { kind: 'seven_day', percentUsed: 15 }], changed: ['rateLimits'] })
  expect(statuses.at(-1)).toContain('5 ч 57%')
  expect(statuses.at(-1)).toContain('неделя 15%')
})
