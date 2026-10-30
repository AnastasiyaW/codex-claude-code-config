import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Activity, AgentRow, AgentStat, Limits, LimitWindow, Progress, Todo } from '../types'

// Pult: a control strip for Claude Code. Data comes from the engine only
// ($.session.usage(), session.measure, tool calls, subagent list). On disk the mod writes
// handoffs (<project>/.claude/handoffs/<slug>/ plus a line in INDEX.md). No network calls.
// Every feature can be switched off in /config.

const limits = atom({ plugin: 'pult', key: 'limits' } as const, null as Limits | null)
const nudgedFor = atom({ plugin: 'pult', key: 'nudgedFor' } as const, '')
const contextPct = atom({ plugin: 'pult', key: 'contextPct' } as const, null as number | null)
const contextWarned = atom({ plugin: 'pult', key: 'contextWarned' } as const, false)
const chatTokens = atom({ plugin: 'pult', key: 'chatTokens' } as const, null as number | null)
const newChatHinted = atom({ plugin: 'pult', key: 'newChatHinted' } as const, false)
const activity = atom({ plugin: 'pult', key: 'activity' } as const, [] as Activity[])
const todos = atom({ plugin: 'pult', key: 'todos' } as const, [] as Todo[])
const agents = atom({ plugin: 'pult', key: 'agents' } as const, [] as AgentRow[])
// simplification: finished-agent rows live until the session ends; there are only a handful to hundreds.
const agentStats = atom({ plugin: 'pult', key: 'agentStats' } as const, {} as Record<string, AgentStat>)
const tick = atom({ plugin: 'pult', key: 'tick' } as const, 0)
const turnStartedAt = atom({ plugin: 'pult', key: 'turnStartedAt' } as const, null as number | null)
const turnCalls = atom({ plugin: 'pult', key: 'turnCalls' } as const, { count: 0, nudged: false })
const checkpoint = atom({ plugin: 'pult', key: 'checkpoint' } as const, null as { path: string; at: number; why: string } | null)
const busy = atom({ plugin: 'pult', key: 'busy' } as const, null as { text: string; since: number } | null)
const progress = atom({ plugin: 'pult', key: 'progress' } as const, null as Progress | null)

const PROGRESS_TOOL = 'mcp__pult__progress'
const PROGRESS_SPEC = {
  name: 'progress',
  description:
    'Показывает пользователю прогресс текущей задачи в полосе над полем ввода. Вызывай, когда начинаешь работу из 3+ шагов или долгий прогон (план, исследование, ревью, миграция, обучение), и после каждого завершённого шага; при внутреннем прогрессе шага (обработано N из M) — передай sub. Названия короткие, по-русски, как их поймёт человек. Когда всё сделано — done = total. clear: true убирает полосу.',
  inputSchema: {
    type: 'object',
    properties: {
      title: { type: 'string', description: 'Название задачи, 2–5 слов' },
      done: { type: 'integer', minimum: 0, description: 'Сколько шагов сделано' },
      total: { type: 'integer', minimum: 1, description: 'Сколько шагов всего' },
      unit: { type: 'string', description: 'Чего шаги: «этапов», «пунктов», «файлов». По умолчанию «этапов»' },
      now: { type: 'string', description: 'Что делается сейчас, одной фразой' },
      next: { type: 'string', description: 'Что дальше, одной фразой' },
      sub: {
        type: 'object',
        description: 'Прогресс внутри текущего шага',
        properties: { label: { type: 'string' }, done: { type: 'integer', minimum: 0 }, total: { type: 'integer', minimum: 1 } },
        required: ['label', 'done', 'total'],
      },
      counts: {
        type: 'array',
        description: 'Счётчики итогов, например [{label:"доделано",n:9},{label:"открыто",n:1}]',
        items: { type: 'object', properties: { label: { type: 'string' }, n: { type: 'integer' } }, required: ['label', 'n'] },
      },
      clear: { type: 'boolean', description: 'Убрать полосу' },
    },
  },
  isDeferred: false,
} as const

// Default threshold for suggesting /compact or a new chat. It sits just below a 400k
// auto-compact setting; long main chats are where most of the weekly usage goes.
export const NEW_CHAT_TOKENS = 350_000

export function newChatLine(tokens: number | null, threshold: number): string | null {
  if (tokens === null || threshold <= 0 || tokens < threshold) return null
  return `контекст ${fmtTokens(tokens)} · скоро сжатие · та же задача: /compact · новая: новый чат`
}

export function newChatHint(tokens: number): string {
  return `pult: контекст этого чата уже ${fmtTokens(tokens)} токенов, и каждый шаг перечитывает его целиком. Текущую работу не прерывай; когда закончишь её, в итоговом ответе одной строкой предложи пользователю выбрать: та же задача — сжать чат (/compact), новая задача — новый чат с хендоффом.`
}

export const NUDGE_AFTER_CALLS = 4
const PROGRESS_NUDGE =
  'pult: в этом ходе уже несколько шагов, а полоса прогресса пуста. Если работа многошаговая — вызови mcp__pult__progress (title, done, total, now, next); если это одна короткая операция — продолжай.'

// Nudge once per turn, only when no progress is active (none, or the last one finished before this turn).
export function shouldNudgeProgress(count: number, nudged: boolean, p: Progress | null, turnStartedAtMs: number): boolean {
  if (nudged || count < NUDGE_AFTER_CALLS) return false
  return p === null || (p.done >= p.total && p.at < turnStartedAtMs)
}

const PROGRESS_RULE =
  'В этой сессии есть инструмент mcp__pult__progress: пользователь видит прогресс задачи в полосе над вводом. Работа из трёх и более шагов (план, исследование, ревью, миграция, длинный прогон) — вызови его со списком шагов в начале и после каждого шага; сам план в тексте ответа он не заменяет.'

const PANE = 'pult-activity'
const FRESH_MS = 25 * 60 * 1000
// The "writing handoff" flag lives in $.state and survives a module reload mid-write;
// older than this it is treated as abandoned.
const BUSY_STALE_MS = 5 * 60 * 1000

const AGENT_WORD: Record<string, string> = {
  pending: 'ждёт запуска',
  running: 'работает',
  waiting: 'ждёт',
  idle: 'простаивает',
  completed: 'готов',
  failed: 'упал',
  killed: 'остановлен',
}

const HANDOFF_PROMPT = `Напиши хендофф этой сессии по правилу session-handoff, чтобы новая сессия продолжила без потерь.
Формат (markdown, по-русски, до 1500 токенов, описывай что верно сейчас, а не хронику):
# Handoff: <тема> (<дата время>)
## Goal — что и зачем делаем.
## Done — конкретные результаты с абсолютными путями, коммитами.
## What did NOT work — что не сработало и почему (обязательно, даже если всё прошло).
## Current state — что работает, что сломано (с текстом ошибки), что ждёт внешнего.
## Key decisions — выбор и причина.
## Next step — одно конкретное действие.
Только сам хендофф, без вступления.`

type Options = {
  status_line?: boolean
  handoff_nudge?: boolean
  nudge_percent?: number
  context_percent?: number
  new_chat_tokens?: number
  compact_handoff?: boolean
  activity_pane?: boolean
  activity_band?: boolean
  progress_band?: boolean
  notify?: boolean
  notify_minutes?: number
}

export function fmtReset(epochSec: number, nowMs: number): string {
  const d = new Date(epochSec * 1000)
  const days = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const left = epochSec * 1000 - nowMs
  if (left <= 0) return 'сброс прошёл'
  if (left < 24 * 3600 * 1000) return `сброс в ${hm}`
  return `сброс ${days[d.getDay()]} ${hm}`
}

// Limit windows from the API response: kind five_hour / seven_day, reset as an ISO string.
export function limitsFromApi(rows: readonly { kind: string; percentUsed: number; resetsAt?: string }[], nowMs: number): Limits | null {
  const win = (kind: string): LimitWindow | null => {
    const r = rows.find(x => x.kind === kind)
    if (!r) return null
    const ms = r.resetsAt ? Date.parse(r.resetsAt) : NaN
    return { pct: Math.round(r.percentUsed), resetsAt: Number.isFinite(ms) ? Math.floor(ms / 1000) : 0 }
  }
  const five = win('five_hour')
  const week = win('seven_day')
  return five || week ? { at: Math.floor(nowMs / 1000), five, week } : null
}

// Handoff folder name: kebab-case of the project root name.
export function projectSlug(root: string): string {
  const base = root.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? ''
  const slug = base.toLowerCase().replace(/[^a-z0-9а-яё]+/g, '-').replace(/^-+|-+$/g, '')
  return slug || 'project'
}

const pad = (n: number) => String(n).padStart(2, '0')
export const clockTime = (ms: number) => `${pad(new Date(ms).getHours())}:${pad(new Date(ms).getMinutes())}`

// YYYY-MM-DD_HH-MM_<first 8 chars of session id>.md
export function handoffName(nowMs: number, sessionId: string): string {
  const d = new Date(nowMs)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}_${sessionId.slice(0, 8)}.md`
}

export function indexLine(nowMs: number, sessionId: string, slug: string, name: string, why: string): string {
  const d = new Date(nowMs)
  const when = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return `- ${when} | ${sessionId.slice(0, 8)} | ${slug} | хендофф модом pult: ${why} | [${name.replace(/\.md$/, '')}](${slug}/${name})`
}

const short = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)
const fileName = (p: unknown) => (typeof p === 'string' ? p.replace(/\\/g, '/').split('/').pop() ?? p : '')

export function toolLabel(tool: string, input: Record<string, unknown>): string {
  const s = (k: string) => (typeof input[k] === 'string' ? (input[k] as string) : '')
  if (tool === 'Bash' || tool === 'PowerShell') return short((s('description') || s('command')).replace(/\s+/g, ' '), 70)
  if (['Read', 'Edit', 'Write', 'NotebookEdit'].includes(tool)) return fileName(input.file_path ?? input.notebook_path)
  if (tool === 'Grep' || tool === 'Glob') return short(s('pattern'), 60)
  if (tool === 'Agent') return short(s('description') || s('prompt'), 60)
  if (tool === 'WebFetch') return short(s('url'), 60)
  if (tool === 'WebSearch') return short(s('query'), 60)
  if (tool === 'Skill') return s('skill')
  return ''
}

type StepUsage = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number; model: string }

// Context = the whole input of the last response. Spend is approximate, in plain-input-token units:
// cache read x0.1, cache write x2, output x5 (per-model price differences ignored).
export function stepStat(prev: AgentStat | undefined, u: StepUsage): AgentStat {
  const contextTokens = u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens
  const cost = u.input_tokens + 0.1 * u.cache_read_input_tokens + 2 * u.cache_creation_input_tokens + 5 * u.output_tokens
  return { model: u.model, contextTokens, spent: (prev?.spent ?? 0) + cost }
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(Math.round(n))
}

export function modelWord(id: string): string {
  return id.match(/fable|opus|sonnet|haiku/i)?.[0]?.toLowerCase() ?? id
}

export function agentBrief(st: AgentStat): string {
  return `${modelWord(st.model)}${st.contextTokens ? ` ${fmtTokens(st.contextTokens)}` : ''}`
}

const isBusyAgent = (a: AgentRow) => a.status === 'running' || a.status === 'waiting' || a.status === 'pending'

export function fmtDur(ms: number): string {
  const sec = Math.max(0, Math.round(ms / 1000))
  if (sec < 60) return `${sec} с`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} мин ${sec % 60} с`
  return `${Math.floor(min / 60)} ч ${min % 60} мин`
}

type $ = EngineInterface

async function refresh($: $, opt: Options) {
  if (opt.status_line !== false || opt.handoff_nudge !== false) {
    const now = await $.clock.now()
    // session.measure may not arrive in a desktop-app session, so ask the engine after every turn.
    const usage = await $.session.usage().catch(() => null)
    if (usage?.context.percent !== undefined) await update($, contextPct, () => usage.context.percent ?? null)
    if (usage?.context.tokens !== undefined) await update($, chatTokens, () => usage.context.tokens ?? null)
    const fromApi = usage ? limitsFromApi(usage.rateLimits, now) : null
    if (fromApi) await update($, limits, () => fromApi)
  }
  await paint($, opt)
}

async function paint($: $, opt: Options) {
  const threshold = opt.nudge_percent ?? 90
  const now = await $.clock.now()
  const lim = await read($, limits)
  const ctx = await read($, contextPct)
  if (opt.status_line !== false) {
    const bits: string[] = []
    if (ctx !== null) bits.push(`контекст ${ctx}%`)
    if (lim?.week) bits.push(`неделя ${lim.week.pct}% · ${fmtReset(lim.week.resetsAt, now)}`)
    if (lim?.five) bits.push(`5 ч ${lim.five.pct}%`)
    const busyAgents = (await read($, agents)).filter(isBusyAgent)
    if (busyAgents.length) {
      const stats = await read($, agentStats)
      const briefs = busyAgents.flatMap(a => (stats[a.id] ? [agentBrief(stats[a.id]!)] : []))
      bits.push(`агенты ${busyAgents.length}${briefs.length ? `: ${briefs.join(', ')}` : ''}`)
    }
    $.ui.status(bits.length ? bits.join(' · ') : undefined)
  }
  if (opt.handoff_nudge !== false && lim) {
    const hot = [lim.week, lim.five].find(w => w && w.pct >= threshold && w.resetsAt * 1000 > now)
    if (hot) {
      const key = String(hot.resetsAt)
      if ((await read($, nudgedFor)) !== key) {
        await update($, nudgedFor, () => key)
        $.ui.toast(`Лимит ${hot.pct}% — пора записать хендофф: /save-handoff`)
      }
    }
  }
  if (opt.handoff_nudge !== false && ctx !== null && ctx >= (opt.context_percent ?? 80) && !(await read($, contextWarned))) {
    await update($, contextWarned, () => true)
    $.ui.toast(`Контекст заполнен на ${ctx}% — запишите хендофф: /save-handoff`)
  }
}

// Model-free draft for when the fork did not answer (e.g. the transcript no longer fits the
// window, which is often why compaction runs). A draft beats nothing.
export function draftHandoff(messages: readonly { role: string; text: string }[], why: string, reason: string): string {
  // Slash-command service lines (<command-name>...) are not user messages.
  const said = messages.filter(m => m.role === 'user' && m.text.trim() && !m.text.trimStart().startsWith('<command-')).slice(-6)
  const last = [...messages].reverse().find(m => m.role === 'assistant' && m.text.trim())
  return [
    `# Handoff (черновик без модели: ${reason})`,
    '',
    `Записан модом pult ${why}; модель хендофф не написала, поэтому здесь только последние реплики.`,
    'Первым делом в новой сессии — дописать этот хендофф по правилу session-handoff.',
    '',
    '## Последние запросы',
    ...said.map(m => `- ${short(m.text.replace(/\s+/g, ' ').trim(), 400)}`),
    '',
    '## Последний ответ',
    last ? short(last.text.trim(), 2000) : '(нет)',
    '',
  ].join('\n')
}

// A fresh (younger than FRESH_MS) handoff of THIS session; a parallel session's file does not count.
async function hasFreshHandoff($: $, dir: string, sid: string, now: number): Promise<boolean> {
  const mine = `_${sid.slice(0, 8)}`
  const list = await $.fs.list(dir).catch(() => [])
  return list.some(f => f.kind === 'file' && /\.md$/.test(f.name) && f.name.replace(/(-\d+)?\.md$/, '').endsWith(mine) && now - f.mtimeMs < FRESH_MS)
}

// A second handoff in the same minute gets a -2, -3... suffix.
async function freeName($: $, dir: string, name: string): Promise<string> {
  for (let n = 1; n < 100; n++) {
    const candidate = n === 1 ? name : name.replace(/\.md$/, `-${n}.md`)
    if (!(await $.fs.exists(`${dir}/${candidate}`))) return candidate
  }
  return name
}

// A cloned repository may plant a link at .claude/handoffs or INDEX.md; the mod writes only where the
// path really lands inside the project, and never through a link to a file.
// simplification: checked right before each write, not atomically with it.
async function landsInside($: $, rootReal: string, path: string): Promise<boolean> {
  const fold = /^[A-Za-z]:[\\/]/.test(rootReal) ? (p: string) => p.toLowerCase() : (p: string) => p
  const norm = (p: string) => fold(p.replace(/\\/g, '/').replace(/\/+$/, ''))
  const root = norm(rootReal)
  const isUnder = (p?: string) => p !== undefined && (norm(p) === root || norm(p).startsWith(`${root}/`))
  // Walk up from the file to the first level that exists. A level may be missing (the write creates
  // it) but never a link stat cannot follow: the folder listing shows such an entry as it stands.
  // Names compare case-insensitively everywhere: a false refusal costs nothing.
  for (let child = path; ; ) {
    const cut = Math.max(child.lastIndexOf('/'), child.lastIndexOf('\\'))
    if (cut <= 0) return false
    const dir = child.slice(0, cut)
    const name = child.slice(cut + 1).toLowerCase()
    const entries = await $.fs.list(dir).catch(() => undefined)
    if (entries === undefined && (await $.fs.exists(dir))) return false
    const isLink = (entries ?? []).some(entry => entry.name.toLowerCase() === name && entry.isLink)
    // The file itself is never written through a link, even one into the project (.git/hooks).
    const found = await $.fs.stat(child, { resolve: true }).catch(() => undefined)
    if (found) return (child !== path || !found.isLink) && isUnder(found.realPath)
    if (isLink) return false
    child = dir
  }
}

// The model writes the handoff from the cached transcript. Never throws: returns the outcome as text.
async function writeHandoff($: $, why: string, skipIfFresh: boolean, messages?: readonly { role: string; text: string }[], announce = false): Promise<string> {
  const now = await $.clock.now()
  // Take the flag in one update (it re-reads and retries on a race), so /save-handoff and
  // auto-compaction at the same time cannot write two handoffs.
  let isMine = false
  await update($, busy, held => {
    isMine = !(held && now - held.since < BUSY_STALE_MS)
    return isMine ? { text: 'Пишу хендофф…', since: now } : held
  })
  if (!isMine) return 'Хендофф уже пишется.'
  try {
    const root = (await $.session.root()).replace(/[\\/]+$/, '')
    const slug = projectSlug(root)
    const base = `${root}/.claude/handoffs`
    const sid = await $.session.id()
    if (skipIfFresh && (await hasFreshHandoff($, `${base}/${slug}`, sid, now))) return 'Свежий хендофф этой сессии уже есть — новый не нужен.'
    if ((await $.session.turns()) === 0) return 'Писать нечего: в сессии ещё не было ходов.'
    if (announce) $.ui.toast('Пишу хендофф перед сжатием…')
    const fork = await $.model.fork({ prompt: HANDOFF_PROMPT })
    if (!fork.isAnswered && fork.reason === 'nothing-to-fork') return 'Писать нечего: модель в этой сессии ещё не отвечала.'
    let body: string
    if (fork.isAnswered) {
      body = fork.text.trim()
    } else {
      const rows = messages ?? (await $.session.messages().catch(() => []))
      body = draftHandoff(Array.isArray(rows) ? (rows as { role: string; text: string }[]) : [], why, fork.reason)
    }
    const name = await freeName($, `${base}/${slug}`, handoffName(now, sid))
    const path = `${base}/${slug}/${name}`
    const rootReal = (await $.fs.stat(root, { resolve: true }).catch(() => undefined))?.realPath
    if (rootReal === undefined || !(await landsInside($, rootReal, path))) {
      return 'Хендофф не записан: .claude/handoffs ведёт за пределы проекта или папку проекта не найти.'
    }
    await $.fs.write(path, `<!-- pult: ${why} -->\n\n${body}\n`)
    await update($, checkpoint, () => ({ path, at: now, why }))
    const done = `Хендофф${fork.isAnswered ? '' : '-черновик'} записан: .claude/handoffs/${slug}/${name}`
    // INDEX.md is rewritten whole, so only after a successful read: a locked file
    // (antivirus, sync client) must not turn into an empty index.
    const index = `${base}/INDEX.md`
    if (!(await landsInside($, rootReal, index))) return `${done}. INDEX.md не тронут: это ссылка или он ведёт за пределы проекта.`
    let old = '# Handoffs\n'
    if (await $.fs.exists(index)) {
      try {
        old = String(await $.fs.read(index))
      } catch (error) {
        return `${done}. INDEX.md не прочитан (${String(error).slice(0, 60)}) — строку в индекс добавьте вручную.`
      }
    }
    await $.fs.write(index, `${old.replace(/\s*$/, '')}\n${indexLine(now, sid, slug, name, why)}\n`)
    return done
  } catch (error) {
    return `Хендофф не записан: ${String(error).slice(0, 120)}`
  } finally {
    await update($, busy, () => null)
  }
}

async function pollAgents($: $) {
  const list = await $.agent.list().catch(() => [])
  await update($, agents, () => list.map(a => ({ id: a.id, type: a.type, description: a.description, status: a.status })))
}

async function openPane($: $) {
  return $.ui.open({ id: PANE, title: 'Активность' })
}

const tracksActivity = (opt: Options) => opt.activity_band !== false || opt.activity_pane !== false

// mcp__pult__progress input -> band state; null clears it. Garbage input does not throw.
export function parseProgress(input: Record<string, unknown>, at: number, prev: Progress | null): Progress | null {
  if (input.clear === true) return null
  const str = (v: unknown, fallback: string) => (typeof v === 'string' && v.trim() ? v.trim() : fallback)
  const int = (v: unknown, fallback: number) => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.round(v)) : fallback)
  const total = Math.max(1, int(input.total, prev?.total ?? 1))
  const sub = input.sub && typeof input.sub === 'object' ? (input.sub as Record<string, unknown>) : null
  const counts = Array.isArray(input.counts)
    ? input.counts
        .filter((c): c is Record<string, unknown> => !!c && typeof c === 'object')
        .map(c => ({ label: str(c.label, ''), n: int(c.n, 0) }))
        .filter(c => c.label)
        .slice(0, 5)
    : (prev?.counts ?? [])
  return {
    title: str(input.title, prev?.title ?? 'Задача'),
    done: Math.min(total, int(input.done, prev?.done ?? 0)),
    total,
    unit: str(input.unit, prev?.unit ?? 'этапов'),
    now: str(input.now, ''),
    next: str(input.next, ''),
    sub: sub ? { label: str(sub.label, ''), done: int(sub.done, 0), total: Math.max(1, int(sub.total, 1)) } : null,
    counts,
    at,
  }
}

export function bar(done: number, total: number, width: number): [string, string] {
  const filled = total > 0 ? Math.round((Math.min(done, total) / total) * width) : 0
  return ['█'.repeat(filled), '░'.repeat(width - filled)]
}

const fmtNum = (n: number) => n.toLocaleString('ru-RU')

export type BandLine = { key: string; text: string; tone: 'plain' | 'ask' | 'dim' }

// Short calls (Read, Grep take a fraction of a second) do not flicker the band.
export const CALL_SHOW_MS = 3000

export function limitWarning(lim: Limits | null, nowMs: number, threshold: number): string | null {
  if (!lim) return null
  const windows: { name: string; w: LimitWindow }[] = []
  if (lim.week) windows.push({ name: 'неделя', w: lim.week })
  if (lim.five) windows.push({ name: '5 ч', w: lim.five })
  const hot = windows.filter(x => x.w.pct >= threshold && x.w.resetsAt * 1000 > nowMs).sort((a, b) => b.w.pct - a.w.pct)[0]
  return hot ? `⚠ ${hot.name} ${hot.w.pct}% · ${fmtReset(hot.w.resetsAt, nowMs)} · запишите хендофф: /save-handoff` : null
}

// "What's running now" band: at most three lines (call, plan, subagents). Empty when idle.
export function bandLines(now: number, list: readonly Activity[], plan: readonly Todo[], subs: readonly AgentRow[], stats: Readonly<Record<string, AgentStat>> = {}): BandLine[] {
  const out: BandLine[] = []
  const running = list.filter(a => a.endedAt === null)
  const asked = running.filter(a => a.isAsked)
  const slow = running.filter(a => now - a.startedAt >= CALL_SHOW_MS)
  const head = asked[asked.length - 1] ?? slow[slow.length - 1]
  if (head) {
    const more = running.length > 1 ? ` (+${running.length - 1})` : ''
    const what = `${head.tool} ${fmtDur(now - head.startedAt)}${head.label ? ` · ${head.label}` : ''}${more}`
    out.push(head.isAsked ? { key: 'call', text: `⏸ запрошено подтверждение · ${what}`, tone: 'ask' } : { key: 'call', text: `▶ ${what}`, tone: 'plain' })
  }
  const left = plan.filter(t => t.status !== 'completed')
  if (plan.length && left.length) {
    const doing = plan.find(t => t.status === 'in_progress')
    out.push({ key: 'plan', text: `План ${plan.length - left.length}/${plan.length}${doing ? ` · ${doing.content}` : ''}`, tone: 'dim' })
  }
  const busyAgents = subs.filter(isBusyAgent)
  if (busyAgents.length) {
    const briefs = busyAgents.flatMap(a => (stats[a.id] ? [agentBrief(stats[a.id]!)] : []))
    const one = busyAgents[0]!
    const oneStat = stats[one.id]
    const word = busyAgents.length === 1
      ? `${one.type} · ${one.description}${oneStat ? ` · ${agentBrief(oneStat)}` : ''}`
      : `${busyAgents.length} работают${briefs.length ? ` · ${briefs.join(', ')}` : ''}`
    out.push({ key: 'agents', text: `Субагенты: ${word}`, tone: 'dim' })
  }
  return out
}

// Close main-loop rows whose end was never recorded (module reloaded mid-call).
// Subagent and background calls outlive the turn, so they are left alone.
async function closeOpenRows($: $) {
  const now = await $.clock.now()
  await update($, activity, list => (list.some(a => a.endedAt === null && !a.agentId) ? list.map(a => (a.endedAt === null && !a.agentId ? { ...a, endedAt: now } : a)) : list))
}

export const register: Register = (on, options) => {
  const opt = (options ?? {}) as Options
  let timer: { cancel: () => void } | undefined

  on('session.start', async ($, e, next) => {
    await update($, busy, () => null)
    // Command names must be literal and use only Latin letters, digits, _ and - (validate reads them
    // from source): the engine rejects a Cyrillic name and then skips the whole session.start handler.
    if (opt.handoff_nudge !== false) {
      await $.command.register({ name: 'handoff', description: 'Подставить в поле ввода просьбу написать хендофф сессии' })
    }
    if (opt.compact_handoff !== false) {
      await $.command.register({ name: 'save-handoff', description: 'Записать хендофф сессии сейчас, не прерывая работу (.claude/handoffs/<проект>/)' })
    }
    if (opt.activity_pane !== false) {
      await $.command.register({ name: 'activity', description: 'Панель: что выполняется, что ждёт подтверждения, субагенты, план' })
    }
    if (opt.progress_band !== false) await $.tool.register(PROGRESS_SPEC)
    if (tracksActivity(opt)) {
      // Timers and the subagent list refresh every 2 s while something runs.
      // session.start can fire more than once (/clear, resume): cancel the previous timer.
      timer?.cancel()
      timer = $.clock.every(2000, async () => {
        const list = await read($, activity)
        const running = list.some(a => a.endedAt === null)
        const live = (await read($, agents)).some(a => a.status === 'running' || a.status === 'waiting' || a.status === 'pending')
        if (running || live) {
          await pollAgents($)
          await update($, tick, n => n + 1)
        }
      })
    }
    const out = await next(e)
    await refresh($, opt)
    return out
  })

  // A refresh failure must never block sending the prompt.
  on('prompt.submit', async ($, e, next) => {
    void refresh($, opt)
    // A finished task showed its check mark; the next message clears the band.
    const p = await read($, progress)
    if (p && p.done >= p.total) await update($, progress, () => null)
    return next(e)
  }).catch(($, e, next) => next(e))

  // The progress rule goes into the system prompt, otherwise the model forgets the band exists.
  on('prompt.compose', async ($, e, next) => {
    const out = await next(e)
    if (opt.progress_band === false || !e.tools.includes(PROGRESS_TOOL)) return out
    return { sections: [...out.sections, { id: 'pult:progress', text: PROGRESS_RULE, scope: 'session' as const }] }
  }).catch(($, e, next) => next(e))

  on('tool.call', { tool: PROGRESS_TOOL }, async ($, e) => {
    const now = await $.clock.now()
    const input = e as unknown as Record<string, unknown>
    await update($, progress, prev => parseProgress(input, now, prev))
    const p = await read($, progress)
    return { result: p ? `Полоса: ${p.title} ${p.done}/${p.total}` : 'Полоса убрана' }
  })

  on('turn.start', async ($, e, next) => {
    const now = await $.clock.now()
    await update($, turnStartedAt, () => now)
    await update($, turnCalls, () => ({ count: 0, nudged: false }))
    return next(e)
  })

  // A subagent turn also ends with turn.complete (with agentId) but has no turn.start;
  // it must not touch the main turn's timing.
  on('turn.complete', async ($, e, next) => {
    if (e.agentId) return next(e)
    const out = await next(e)
    const started = await read($, turnStartedAt)
    await update($, turnStartedAt, () => null)
    await closeOpenRows($)
    if (opt.notify !== false && started !== null) {
      const took = (await $.clock.now()) - started
      if (took >= (opt.notify_minutes ?? 3) * 60 * 1000) {
        const word = e.reason === 'answer' ? 'Ход закончен' : e.reason === 'aborted' ? 'Ход прерван' : 'Ход оборвался'
        void $.ui.notify(`${word} за ${fmtDur(took)}`, { title: 'Claude Code' }).catch(() => undefined)
      }
    }
    await refresh($, opt)
    return out
  })

  // session.measure covers only the main chat, so subagent context is taken from each of its responses.
  on('turn.step', async function* ($, e, next) {
    const id = e.agentId
    // The model is known before the response; an agent's first response can take minutes.
    if (id) {
      await update($, agentStats, all => ({ ...all, [id]: { ...(all[id] ?? { contextTokens: 0, spent: 0 }), model: e.model } }))
      await pollAgents($)
      await paint($, opt)
    }
    const out = yield* next(e)
    const u = out.usage
    if (id && u) {
      await update($, agentStats, all => ({ ...all, [id]: stepStat(all[id], u) }))
      await paint($, opt)
    }
    return out
  })

  on('session.measure', async ($, e, next) => {
    const out = await next(e)
    if (e.context.percent !== undefined) await update($, contextPct, () => e.context.percent ?? null)
    if (e.context.tokens !== undefined) await update($, chatTokens, () => e.context.tokens ?? null)
    const fromApi = limitsFromApi(e.rateLimits, await $.clock.now())
    if (fromApi) await update($, limits, () => fromApi)
    await paint($, opt)
    return out
  })

  // Handoff before compaction of the main chat (manual or auto). A mod error never blocks compaction.
  on('session.compact', async ($, e, next) => {
    if (opt.compact_handoff !== false && !e.agentId && (e.trigger === 'manual' || e.trigger === 'auto')) {
      const said = await writeHandoff($, e.trigger === 'auto' ? 'перед автосжатием' : 'перед /compact', true, e.messages, true)
      $.ui.toast(said)
    }
    const out = await next(e)
    await update($, contextWarned, () => false)
    await update($, chatTokens, () => null)
    await update($, newChatHinted, () => false)
    return out
  }).catch(($, e, next) => next(e))

  on('tool.call', async ($, e, next) => {
    if (!tracksActivity(opt) || e.tool === PROGRESS_TOOL) return next(e)
    const id = e.tool_use_id ?? `${e.tool}-${await $.clock.now()}`
    const input = e as unknown as Record<string, unknown>
    const row: Activity = {
      id,
      agentId: e.agentId ?? null,
      tool: String(e.tool),
      label: toolLabel(String(e.tool), input),
      startedAt: await $.clock.now(),
      endedAt: null,
      isError: false,
      isAsked: false,
    }
    await update($, activity, list => [...list, row].slice(-200))
    if (e.tool === 'TodoWrite' && Array.isArray(input.todos)) {
      await update($, todos, () => (input.todos as Todo[]).map(t => ({ content: t.content, status: t.status })))
    }
    if (e.tool === 'Agent') void pollAgents($)
    let nudge = false
    if (opt.progress_band !== false && !e.agentId) {
      const startedAt = (await read($, turnStartedAt)) ?? 0
      const p = await read($, progress)
      let calls = { count: 0, nudged: false }
      await update($, turnCalls, c => (calls = { count: c.count + 1, nudged: c.nudged }))
      nudge = shouldNudgeProgress(calls.count, calls.nudged, p, startedAt)
      if (nudge) await update($, turnCalls, c => ({ ...c, nudged: true }))
    }
    // Once per chat: the model cannot see its own context size.
    let chatHint: string | null = null
    if (!e.agentId) {
      const tokens = await read($, chatTokens)
      if (newChatLine(tokens, opt.new_chat_tokens ?? NEW_CHAT_TOKENS) && tokens !== null && !(await read($, newChatHinted))) {
        await update($, newChatHinted, () => true)
        chatHint = newChatHint(tokens)
      }
    }
    let isError = true
    try {
      const ran = await next(e)
      isError = ('deny' in ran && ran.deny !== undefined) || Boolean(ran.isError)
      const hints = [nudge ? PROGRESS_NUDGE : null, chatHint].filter((h): h is string => h !== null)
      if (hints.length && !('deny' in ran && ran.deny !== undefined)) return { ...ran, context: [...(ran.context ?? []), ...hints] }
      return ran
    } finally {
      const ended = await $.clock.now()
      await update($, activity, list => list.map(a => (a.id === id ? { ...a, endedAt: ended, isError } : a)))
    }
  }).catch(($, e, next) => next(e))

  // A permission dialog shown to the HUMAN (not the auto-mode classifier). The event has no
  // tool_use_id, so the latest running call of that tool is marked.
  on('classic.PermissionRequest', async ($, e, next) => {
    const out = await next(e)
    // The user's own hook already decided (allow/deny): no dialog will appear.
    if (out.decision) return out
    const tool = e.tool_name
    const agentId = e.agent_id ?? null
    await update($, activity, list => {
      const last = [...list].reverse().find(a => a.endedAt === null && a.tool === tool && a.agentId === agentId)
      return last ? list.map(a => (a === last ? { ...a, isAsked: true } : a)) : list
    })
    if (opt.notify !== false) {
      const label = toolLabel(tool, (e.tool_input ?? {}) as Record<string, unknown>)
      void $.ui.notify(`Ждёт подтверждения: ${tool}${label ? ` · ${label}` : ''}`, { title: 'Claude Code' }).catch(() => undefined)
    }
    return out
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'handoff' }, async $ => {
    await $.prompt.fill({
      text: 'Напиши хендофф этой сессии по правилу session-handoff: цель, что сделано, что не сработало, текущее состояние, решения, один следующий шаг.',
      mode: 'replace',
    })
    return { text: 'Просьба о хендоффе в поле ввода — отправьте, когда удобно. Без отдельного хода: /save-handoff.' }
  })

  on('command.run', { command: 'save-handoff' }, async $ => ({ text: await writeHandoff($, 'по команде /save-handoff', false) }))

  on('command.run', { command: 'activity' }, async $ => {
    await pollAgents($)
    const opened = await openPane($)
    return { text: opened.isPlaced ? 'Панель «Активность» открыта.' : 'Панель не поместилась — расширьте окно.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    await read($, tick)
    const now = await $.clock.now()
    const list = await read($, activity)
    const plan = await read($, todos)
    const subs = (await read($, agents)).filter(a => a.status !== 'completed' || list.some(x => x.endedAt === null))
    const stats = await read($, agentStats)
    const running = list.filter(a => a.endedAt === null)
    const done = list.filter(a => a.endedAt !== null).slice(-8).reverse()
    const ctx = await read($, contextPct)
    const cp = await read($, checkpoint)
    const doing = await read($, busy)
    const width = Math.max(20, (e.props.bodyColumns ?? 40) - 2)
    const line = (s: string) => short(s, width)
    return (
      <Box flexDirection="column">
        {(ctx !== null || cp) && (
          <Text dimColor>{line([ctx !== null ? `контекст ${ctx}%` : '', cp ? `хендофф в ${clockTime(cp.at)}` : ''].filter(Boolean).join(' · '))}</Text>
        )}
        {doing && <Text color="yellow">{doing.text}</Text>}
        <Text bold>Сейчас</Text>
        {running.length === 0 && <Text dimColor>ничего не выполняется</Text>}
        {running.map(a => (
          <Text color={a.isAsked ? 'yellow' : undefined}>
            {line(`${a.isAsked ? '⏸ запрошено подтверждение' : '▶'} ${a.tool} ${fmtDur(now - a.startedAt)}${a.label ? ` · ${a.label}` : ''}`)}
          </Text>
        ))}
        {subs.length > 0 && <Text bold>Субагенты</Text>}
        {subs.map(a => {
          const st = stats[a.id]
          const size = st ? ` · ${agentBrief(st)}${st.spent ? ` · расход ${fmtTokens(st.spent)}` : ''}` : ''
          return <Text dimColor={a.status === 'completed'}>{line(`${AGENT_WORD[a.status] ?? a.status} · ${a.type} · ${a.description}${size}`)}</Text>
        })}
        {plan.length > 0 && <Text bold>План</Text>}
        {plan.map(t => (
          <Text dimColor={t.status === 'completed'}>{line(`${t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '▶' : '·'} ${t.content}`)}</Text>
        ))}
        {done.length > 0 && <Text bold>Недавно</Text>}
        {done.map(a => (
          <Text dimColor color={a.isError ? 'red' : undefined}>
            {line(`${a.isError ? '✗' : '✓'} ${a.tool} ${fmtDur((a.endedAt ?? now) - a.startedAt)}${a.label ? ` · ${a.label}` : ''}`)}
          </Text>
        ))}
      </Box>
    )
  })

  // Band above the prompt: limit and context warnings, model progress, then "what's running now".
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    let live: BandLine[] = []
    const now = await $.clock.now()
    if (opt.activity_band !== false) {
      await read($, tick)
      live = bandLines(now, await read($, activity), await read($, todos), await read($, agents), await read($, agentStats))
    }
    const warn = opt.handoff_nudge !== false ? limitWarning(await read($, limits), now, opt.nudge_percent ?? 90) : null
    const p = opt.progress_band !== false ? await read($, progress) : null
    // Model progress outranks the TodoWrite plan: never draw two scales.
    if (p) live = live.filter(l => l.key !== 'plan')
    const chatLine = newChatLine(await read($, chatTokens), opt.new_chat_tokens ?? NEW_CHAT_TOKENS)
    if (!live.length && !p && !warn && !chatLine) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const width = Math.max(20, e.props.bodyColumns)
    const barWidth = Math.max(8, Math.min(24, Math.floor(width / 4)))
    const isDone = p !== null && p.done >= p.total
    const [fill, rest0] = p ? bar(p.done, p.total, barWidth) : ['', '']
    const [subFill, subRest] = p?.sub ? bar(p.sub.done, p.sub.total, barWidth) : ['', '']
    return (
      <Box flexDirection="column">
        {warn && (
          <Text key="limit" color="warning">
            {short(warn, width)}
          </Text>
        )}
        {chatLine && (
          <Text key="new-chat" color="warning">
            {short(chatLine, width)}
          </Text>
        )}
        {p && (
          <Box key="progress-head">
            <Text bold color={isDone ? 'success' : undefined}>{`${isDone ? '✓ ' : ''}${short(p.title, 40)} `}</Text>
            <Text color={isDone ? 'success' : 'claude'}>{fill}</Text>
            <Text dimColor>{rest0}</Text>
            <Text>{` ${p.done}/${p.total} ${p.unit}`}</Text>
            {p.counts.length > 0 && <Text dimColor>{` · ${p.counts.map(c => `${c.label} ${c.n}`).join(' · ')}`}</Text>}
          </Box>
        )}
        {p && p.now && !isDone && <Text key="progress-now">{short(`сейчас: ${p.now}`, width)}</Text>}
        {p && p.sub && !isDone && (
          <Box key="progress-sub">
            <Text>{`  ▸ ${short(p.sub.label, 30)} `}</Text>
            <Text color="claude">{subFill}</Text>
            <Text dimColor>{subRest}</Text>
            <Text>{` ${fmtNum(p.sub.done)}/${fmtNum(p.sub.total)} ${Math.round((Math.min(p.sub.done, p.sub.total) / p.sub.total) * 100)}%`}</Text>
          </Box>
        )}
        {p && p.next && !isDone && <Text key="progress-next" dimColor>{short(`дальше: ${p.next}`, width)}</Text>}
        {live.map(l => (
          <Text key={l.key} color={l.tone === 'ask' ? 'yellow' : undefined} dimColor={l.tone === 'dim'}>
            {short(l.text, width)}
          </Text>
        ))}
      </Box>
    )
  })
}
