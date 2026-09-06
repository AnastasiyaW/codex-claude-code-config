// workflow-template.js — аннотированный эталон со всеми нашими паттернами.
// Копируй секции по нужде. Это reference, не запускаемая команда (хотя синтаксис валиден).
// Валидация L1: node scripts/validate.mjs. В скрипте недопустимы недетерминизм (системные
// часы, генератор случайных чисел) и прямой fs/shell - даже упоминанием точных имён API в
// строках/комментах (рантайм сканирует исходник подстрокой, не AST - см. SKILL).

export const meta = {
  name: 'template',
  description: 'Эталонный workflow со всеми паттернами (retry, multisample, error policy, .runs)',
  phases: [
    { title: 'Find', detail: 'параллельные finders' },
    { title: 'Verify', detail: 'adversarial проверка находок' },
    { title: 'Report', detail: 'карточки + сводка' },
  ],
}

// ── Schemas (валидируют вывод агента, дают авто-ретрай на mismatch) ──────────
const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          title: { type: 'string' },
          file: { type: 'string' },
          severity: { type: 'string', enum: ['low', 'medium', 'high', 'critical'] },
        },
        required: ['id', 'title', 'severity'],
      },
    },
  },
  required: ['findings'],
}
const VERDICT = {
  type: 'object',
  properties: {
    real: { type: 'boolean' },
    confidence: { type: 'number' },
    reason: { type: 'string' },
  },
  required: ['real', 'confidence'],
}

// ── Gap 1: retry только контролируемого throw; null сохраняет pending identity ──
async function withRetry(makeAgent, n = 2, baseLabel = 'task') {
  for (let attempt = 0; attempt <= n; attempt++) {
    try {
      const r = await makeAgent(attempt)
      // null = stop или unrecoverable API error: не знаем, что безопасно повторять.
      if (r == null) return null
      return r
    } catch (e) {
      if (attempt === n) {
        log(`${baseLabel}: исчерпаны ретраи (${e && e.message ? e.message : e})`)
        return null
      }
    }
  }
  return null
}

// ── Gap 2: multisampling + голосование большинством (чистая функция) ─────────
function majority(items, keyFn) {
  const counts = new Map()
  for (const it of items) {
    const k = keyFn(it)
    counts.set(k, (counts.get(k) || 0) + 1)
  }
  let best = null
  let bestN = 0
  for (const [k, n] of counts) if (n > bestN) { best = k; bestN = n }
  return { value: best, votes: bestN, total: items.length }
}

// ── Gap 2: каждый sample/judge сохраняет identity; null не теряется ──────────
async function multisample(makePrompt, { n = 3, judge = null, label = 'sample', schema, scoreSchema } = {}) {
  const inputIds = Array.from({ length: n }, (_, index) => `${label}#${index}`)
  const raw = await parallel(inputIds.map((inputId, index) => () =>
    agent(makePrompt(index), { label: `sample:${inputId}`, schema })))
  const pending = []
  const samples = []
  raw.forEach((result, index) => {
    if (result == null) pending.push(`sample:${inputIds[index]}`)
    else samples.push({ inputId: inputIds[index], result })
  })
  if (pending.length || !judge) return {
    status: pending.length ? 'INCOMPLETE' : 'COMPLETE', pending, samples,
  }
  const rawScores = await parallel(samples.map((sample) => () =>
    agent(judge(sample.result), { label: `judge:${sample.inputId}`, schema: scoreSchema })))
  const scores = []
  rawScores.forEach((result, index) => {
    if (result == null) pending.push(`judge:${samples[index].inputId}`)
    else scores.push({ inputId: samples[index].inputId, result })
  })
  return { status: pending.length ? 'INCOMPLETE' : 'COMPLETE', pending, samples, scores }
}

// ── runId из args (в скрипте нет доступа к часам) — штампует main-loop перед запуском ─
const runId = (args && args.runId) || 'run-unstamped'
const target = (args && args.target) || 'src/'
log(`template flow стартует: target=${target}, runId=${runId}`)

// ── Phase Find — параллельные finders с разными линзами + retry ──────────────
const FINDERS = [
  { key: 'security', lens: 'уязвимости, инъекции, утечки секретов' },
  { key: 'logic', lens: 'логические ошибки, граничные случаи' },
  { key: 'perf', lens: 'неэффективности, N+1, лишние аллокации' },
]
const pending = new Set()
const finderResults = await parallel(
  FINDERS.map((f) => () =>
    withRetry(
      (att) =>
        agent(`Просканируй ${target} на: ${f.lens}. Верни находки.`, {
          label: `find:${f.key}#${att}`,
          phase: 'Find',
          schema: FINDINGS,
        }),
      2,
      `find:${f.key}`,
    ),
  ),
)
const found = finderResults.flatMap((result, index) => {
  if (result == null) {
    pending.add(`finder:${FINDERS[index].key}`)
    return []
  }
  return result.findings
})

log(`найдено сырых находок: ${found.length}`)

// ── Барьер ОПРАВДАН: dedup по всему множеству перед дорогой верификацией ──────
const seen = new Set()
const unique = found.filter((f) => {
  const k = `${f.file}:${f.title}`
  if (seen.has(k)) return false
  seen.add(k)
  return true
})

// ── Phase Verify — pipeline (БЕЗ барьера): каждая находка верифицируется ──────
//    + null после pipeline восстанавливаем по исходному item: stage 2 может не запуститься.
const judged = await pipeline(
  unique,
  (f) =>
    agent(`Adversarially проверь находку (по умолчанию real=false если не уверен): ${f.title} в ${f.file}`, {
      label: `verify:${f.id}`,
      phase: 'Verify',
      schema: VERDICT,
    }),
  (v, f) => {
    if (v == null) return { ...f, status: 'verify-failed' }
    if (v.confidence < 0.5) return { ...f, status: 'low-confidence', reason: v.reason }
    return { ...f, status: v.real ? 'confirmed' : 'rejected', reason: v.reason }
  },
)
const resolved = judged.map((result, index) => result == null
  ? { ...unique[index], status: 'verify-failed' }
  : result)
const unresolved = resolved.filter((f) => f.status === 'verify-failed' || f.status === 'low-confidence')
for (const finding of unresolved) pending.add(`verify:${finding.id}`)
const confirmed = resolved.filter((f) => f.status === 'confirmed')
log(`подтверждено: ${confirmed.length} / ${unique.length}`)

// ── Phase Report — Gap 4: агент оформляет карточку на каждый косяк в .runs/ ───
phase('Report')
const cardResults = await parallel(
  confirmed.map((f) => () =>
    agent(
      `Оформи карточку находки в .runs/${runId}/findings/${f.id}.md: ` +
        `заголовок "${f.title}", severity ${f.severity}, файл ${f.file}, ` +
        `+ repro и предложенный фикс. Верни путь файла.`,
      { label: `card:${f.id}`, phase: 'Report' },
    ),
  ),
)
cardResults.forEach((result, index) => {
  if (result == null) pending.add(`card:${confirmed[index].id}`)
})

// Независимая проверка: count и IDs, иначе card success не доказывает нужную карточку.
const audit = await agent(
  `Сосчитай .md файлы в .runs/${runId}/findings/ и верни число и IDs карточек.`,
  {
    label: 'audit:cards',
    phase: 'Report',
    schema: {
      type: 'object',
      properties: { count: { type: 'number' }, ids: { type: 'array', items: { type: 'string' } } },
      required: ['count', 'ids'],
    },
  },
)
const expectedCardIds = new Set(confirmed.map((f) => f.id))
const auditedCardIds = new Set((audit && audit.ids) || [])
const idsMatch = audit && audit.ids.length === expectedCardIds.size &&
  auditedCardIds.size === expectedCardIds.size &&
  [...expectedCardIds].every((id) => auditedCardIds.has(id))
if (!audit || audit.count !== confirmed.length || !idsMatch) {
  pending.add('card-audit')
  log(`⚠️ audit карточек неполный или не совпадает с confirmed`)
}

// COMPLETE разрешён лишь при полном учёте; иначе caller получает конкретный список для resume.
const pendingList = [...pending]
return {
  runId,
  status: pendingList.length ? 'INCOMPLETE' : 'COMPLETE',
  pending: pendingList,
  raw: found.length,
  unique: unique.length,
  confirmed: confirmed.length,
  lowConfidence: resolved.filter((f) => f.status === 'low-confidence').length,
  findings: confirmed,
  unresolved,
}
