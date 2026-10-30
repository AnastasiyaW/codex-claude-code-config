import { expect, test } from 'claude-code/testing'

import type { Activity, Progress } from '../types'
import { newChatLine, stepStat, fmtTokens, modelWord, bandLines, bar, CALL_SHOW_MS, limitWarning, NUDGE_AFTER_CALLS, shouldNudgeProgress, clockTime, draftHandoff, fmtDur, parseProgress, fmtReset, handoffName, indexLine, limitsFromApi, projectSlug, toolLabel } from '../hooks/register'

test('limits from the API response', () => {
  const now = Date.UTC(2026, 9, 13, 12, 0)
  const l = limitsFromApi([
    { kind: 'five_hour', percentUsed: 23.5, resetsAt: '2026-10-13T15:00:00Z' },
    { kind: 'seven_day', percentUsed: 71 },
  ], now)
  expect(l?.at).toBe(now / 1000)
  expect(l?.five).toEqual({ pct: 24, resetsAt: Date.UTC(2026, 9, 13, 15, 0) / 1000 })
  expect(l?.week).toEqual({ pct: 71, resetsAt: 0 })
  expect(limitsFromApi([{ kind: 'spend_limit', percentUsed: 5 }], now)).toBe(null)
})

test('reset time in words', () => {
  const now = Date.UTC(2026, 9, 10, 12, 0)
  expect(fmtReset(now / 1000 - 60, now)).toBe('сброс прошёл')
  expect(fmtReset(now / 1000 + 3600, now).startsWith('сброс в ')).toBe(true)
  expect(fmtReset(now / 1000 + 3 * 86400, now).startsWith('сброс ')).toBe(true)
})

test('handoff file name and INDEX.md line', () => {
  const now = new Date(2026, 9, 13, 9, 5).getTime() // local time
  expect(handoffName(now, '7f5720a1-b99b-485c')).toBe('2026-10-13_09-05_7f5720a1.md')
  expect(indexLine(now, '7f5720a1-b99b', 'my-project', '2026-10-13_09-05_7f5720a1.md', 'перед /compact')).toBe(
    '- 2026-10-13 09:05 | 7f5720a1 | my-project | хендофф модом pult: перед /compact | [2026-10-13_09-05_7f5720a1](my-project/2026-10-13_09-05_7f5720a1.md)',
  )
  expect(projectSlug('D:\\My_Project\\')).toBe('my-project')
  expect(projectSlug('D:/Projects/Notes_App заметки')).toBe('notes-app-заметки')
  expect(projectSlug('/')).toBe('project')
})

test('tool call label', () => {
  expect(toolLabel('Bash', { command: 'git   status\n-sb', description: '' })).toBe('git status -sb')
  expect(toolLabel('Bash', { command: 'x', description: 'Show working tree status' })).toBe('Show working tree status')
  expect(toolLabel('Edit', { file_path: 'C:\\a\\b\\register.tsx' })).toBe('register.tsx')
  expect(toolLabel('Agent', { description: 'Review the diff' })).toBe('Review the diff')
  expect(toolLabel('Bash', { command: 'a'.repeat(200) }).length).toBe(70)
  expect(toolLabel('Unknown', {})).toBe('')
})

test('duration in words', () => {
  expect(fmtDur(4_400)).toBe('4 с')
  expect(fmtDur(125_000)).toBe('2 мин 5 с')
  expect(fmtDur(3_900_000)).toBe('1 ч 5 мин')
})

test('activity band: call, permission prompt, plan, subagents', () => {
  const now = 100_000
  const row = (id: string, over: Partial<Activity> = {}): Activity => ({ id, agentId: null, tool: 'Bash', label: 'git status', startedAt: now - 12_000, endedAt: null, isError: false, isAsked: false, ...over })
  expect(bandLines(now, [], [], [])).toEqual([])
  expect(bandLines(now, [row('a', { endedAt: now })], [], [])).toEqual([])
  expect(bandLines(now, [row('a')], [], [])).toEqual([{ key: 'call', text: '▶ Bash 12 с · git status', tone: 'plain' }])
  expect(bandLines(now, [row('a', { isAsked: true }), row('b', { tool: 'Read', label: 'x.ts' })], [], [])[0]).toEqual({
    key: 'call',
    text: '⏸ запрошено подтверждение · Bash 12 с · git status (+1)',
    tone: 'ask',
  })
  const plan = [
    { content: 'Собрать', status: 'completed' as const },
    { content: 'Проверить', status: 'in_progress' as const },
    { content: 'Выложить', status: 'pending' as const },
  ]
  expect(bandLines(now, [], plan, [])).toEqual([{ key: 'plan', text: 'План 1/3 · Проверить', tone: 'dim' }])
  expect(bandLines(now, [], plan.map(t => ({ ...t, status: 'completed' as const })), [])).toEqual([])
  const subs = [{ id: '1', type: 'Explore', description: 'поиск модов', status: 'running' }, { id: '2', type: 'x', description: 'y', status: 'completed' }]
  expect(bandLines(now, [], [], subs)).toEqual([{ key: 'agents', text: 'Субагенты: Explore · поиск модов', tone: 'dim' }])
})

test('new chat is suggested only from the threshold', () => {
  expect(newChatLine(null, 300_000)).toBeNull()
  expect(newChatLine(299_999, 300_000)).toBeNull()
  expect(newChatLine(312_000, 300_000)).toContain('контекст 312k')
  expect(newChatLine(312_000, 0)).toBeNull()
})

test('subagent context and spend come from its responses', () => {
  const u = { input_tokens: 10, cache_read_input_tokens: 80_000, cache_creation_input_tokens: 4_000, output_tokens: 200, model: 'claude-opus-5-5' }
  const first = stepStat(undefined, u)
  expect(first.contextTokens).toBe(84_010)
  expect(first.spent).toBe(10 + 8_000 + 8_000 + 1_000)
  const second = stepStat(first, { ...u, cache_read_input_tokens: 90_000 })
  expect(second.contextTokens).toBe(94_010)
  expect(second.spent).toBe(first.spent + 10 + 9_000 + 8_000 + 1_000)
  expect(fmtTokens(84_010)).toBe('84k')
  expect(fmtTokens(1_250_000)).toBe('1.3M')
  expect(modelWord('claude-opus-5-5')).toBe('opus')
  const a = { id: '1', type: 'Explore', description: 'поиск', status: 'running' }
  const b = { id: '2', type: 'x', description: 'y', status: 'running' }
  const stats = { '1': first }
  expect(bandLines(0, [], [], [a], stats)[0]?.text).toBe('Субагенты: Explore · поиск · opus 84k')
  expect(bandLines(0, [], [], [a, b], stats)[0]?.text).toBe('Субагенты: 2 работают · opus 84k')
  const both = { ...stats, '2': { model: 'sonnet', contextTokens: 0, spent: 0 } }
  expect(bandLines(0, [], [], [a, b], both)[0]?.text).toBe('Субагенты: 2 работают · opus 84k, sonnet')
})

test('draft handoff skips slash-command service lines', () => {
  const d = draftHandoff([{ role: 'user', text: '<command-name>/activity</command-name>' }, { role: 'user', text: 'почини мод' }], 'тест', 'api-error')
  expect(d).toContain('- почини мод')
  expect(d).not.toContain('command-name')
})

test('bar: exactly width cells, overflow does not break it', () => {
  expect(bar(5, 12, 12)).toEqual(['█████', '░░░░░░░'])
  expect(bar(0, 3, 6)).toEqual(['', '░░░░░░'])
  expect(bar(9, 3, 6)).toEqual(['██████', ''])
  const [a, b] = bar(17_639, 29_676, 20)
  expect((a + b).length).toBe(20)
})

test('model progress: fields, defaults, garbage, clear', () => {
  const p = parseProgress({ title: 'Сборка датасета', done: 5, total: 12, now: 'разметка', next: 'проверка', sub: { label: 'Transcribe', done: 17639, total: 29676 } }, 1, null)
  expect(p).toEqual({
    title: 'Сборка датасета', done: 5, total: 12, unit: 'этапов', now: 'разметка', next: 'проверка',
    sub: { label: 'Transcribe', done: 17639, total: 29676 }, counts: [], at: 1,
  })
  // A second call extends the first: title and total carry over.
  const q = parseProgress({ done: 6, counts: [{ label: 'доделано', n: 9 }, { bad: true }, 'x'] }, 2, p)
  expect(q?.title).toBe('Сборка датасета')
  expect(q?.total).toBe(12)
  expect(q?.done).toBe(6)
  expect(q?.counts).toEqual([{ label: 'доделано', n: 9 }])
  expect(q?.sub).toBe(null)
  // done is capped at total; negatives and non-numbers fall back to defaults.
  expect(parseProgress({ title: 't', done: 99, total: 3 }, 3, null)?.done).toBe(3)
  expect(parseProgress({ title: 't', done: 'много', total: -4 }, 3, null)).toMatchObject({ done: 0, total: 1 })
  expect(parseProgress({ clear: true }, 4, p)).toBe(null)
})

test('handoff time on the pane is hours and minutes', () => {
  expect(clockTime(new Date(2026, 9, 13, 20, 41).getTime())).toBe('20:41')
  expect(clockTime(new Date(2026, 9, 13, 9, 5).getTime())).toBe('09:05')
})

test('limit warning: only at threshold and before reset, higher of the two windows', () => {
  const now = Date.UTC(2026, 9, 13, 12, 0)
  const later = now / 1000 + 3 * 86400
  expect(limitWarning(null, now, 90)).toBe(null)
  expect(limitWarning({ at: 0, week: { pct: 89, resetsAt: later }, five: null }, now, 90)).toBe(null)
  expect(limitWarning({ at: 0, week: { pct: 95, resetsAt: now / 1000 - 1 }, five: null }, now, 90)).toBe(null)
  const w = limitWarning({ at: 0, week: { pct: 92, resetsAt: later }, five: { pct: 97, resetsAt: now / 1000 + 600 } }, now, 90)
  expect(w?.startsWith('⚠ 5 ч 97% · сброс в ')).toBe(true)
  expect(w).toContain('/save-handoff')
})

test('a short call stays off the band, a permission prompt shows at once', () => {
  const now = 100_000
  const row = (over: Partial<Activity>): Activity => ({ id: 'a', agentId: null, tool: 'Read', label: 'x.ts', startedAt: now - 500, endedAt: null, isError: false, isAsked: false, ...over })
  expect(bandLines(now, [row({})], [], [])).toEqual([])
  expect(bandLines(now, [row({ startedAt: now - CALL_SHOW_MS })], [], [])[0]?.key).toBe('call')
  expect(bandLines(now, [row({ isAsked: true })], [], [])[0]?.tone).toBe('ask')
})

test('progress nudge: after N calls, once per turn, only without active progress', () => {
  const turn = 1_000
  const live: Progress = { title: 't', done: 1, total: 3, unit: 'этапов', now: '', next: '', sub: null, counts: [], at: 500 }
  expect(shouldNudgeProgress(NUDGE_AFTER_CALLS - 1, false, null, turn)).toBe(false)
  expect(shouldNudgeProgress(NUDGE_AFTER_CALLS, false, null, turn)).toBe(true)
  expect(shouldNudgeProgress(NUDGE_AFTER_CALLS + 3, true, null, turn)).toBe(false)
  expect(shouldNudgeProgress(NUDGE_AFTER_CALLS, false, live, turn)).toBe(false)
  // The previous task finished before this turn: no active band, so nudge.
  expect(shouldNudgeProgress(NUDGE_AFTER_CALLS, false, { ...live, done: 3 }, turn)).toBe(true)
})
