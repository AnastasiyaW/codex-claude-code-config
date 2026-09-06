// Isolated control-flow fixtures; no real agents, filesystem writes or network.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const path = process.argv[2] || new URL('../references/workflow-template.js', import.meta.url)
const source = readFileSync(path, 'utf8').replace(/export\s+const\s+meta\s*=/, 'const meta =')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', source)
const helperSource = source.slice(0, source.indexOf('// ── runId'))

async function fixture(scenario) {
  const calls = new Map()
  const cards = []
  const agent = async (_prompt, { label }) => {
    calls.set(label, (calls.get(label) || 0) + 1)
    if (label.startsWith('find:')) {
      if (scenario === 'finder-null' && label.startsWith('find:logic')) return null
      return { findings: label.startsWith('find:security')
        ? scenario === 'duplicate-card-id'
          ? [
              { id: 'f1', title: 'fixture one', file: 'src/a.cpp', severity: 'high' },
              { id: 'f2', title: 'fixture two', file: 'src/b.cpp', severity: 'high' },
            ]
          : [{ id: 'f1', title: 'fixture', file: 'src/a.cpp', severity: 'high' }]
        : [] }
    }
    if (label.startsWith('verify:')) {
      if (scenario === 'verify-throw') throw new Error('fixture agent failure')
      return { real: true, confidence: 0.9, reason: 'fixture evidence' }
    }
    if (label.startsWith('card:')) {
      if (scenario === 'card-null') return null
      cards.push(label.slice(5))
      return '.runs/fixture/findings/f1.md'
    }
    if (label === 'audit:cards') {
      if (scenario === 'audit-null') return null
      return {
        count: cards.length,
        ids: scenario === 'wrong-card-id' ? ['wrong'] :
          scenario === 'duplicate-card-id' ? ['f1', 'f1'] : cards,
      }
    }
    throw new Error('Unexpected agent label: ' + label)
  }
  const parallel = tasks => Promise.all(tasks.map(async task => {
    try { return await task() } catch { return null }
  }))
  const pipeline = (items, ...stages) => Promise.all(items.map(async (item, index) => {
    let value = item
    for (const stage of stages) {
      try { value = await stage(value, item, index) } catch { return null }
      if (value == null) return null
    }
    return value
  }))
  const output = await run(agent, parallel, pipeline, () => {}, () => {},
    { target: 'src/', runId: 'fixture' })
  return { output, calls: [...calls] }
}

const cases = [
  ['finder-null', 'finder:logic'], ['verify-throw', 'verify:f1'],
  ['card-null', 'card:f1'], ['audit-null', 'card-audit'], ['wrong-card-id', 'card-audit'],
  ['duplicate-card-id', 'card-audit'],
]
for (const [scenario, pendingId] of cases) {
  const observed = await fixture(scenario)
  console.log(JSON.stringify({ scenario, ...observed }))
  assert(observed.output.pending?.includes(pendingId), 'Lost work must retain identity: ' + pendingId)
  assert.equal(observed.output.status, 'INCOMPLETE')
  if (scenario === 'finder-null') {
    assert.equal(observed.calls.filter(([key]) => key.startsWith('find:logic')).length, 1,
      'Null/cancelled agents must not be retried blindly')
  }
}
const success = await fixture('success')
assert.deepEqual(success.output.pending, [])
assert.equal(success.output.status, 'COMPLETE')
assert.equal(success.output.confirmed, 1)
console.log(JSON.stringify({ scenario: 'success', ...success }))

const loadMultisample = new AsyncFunction('agent', 'parallel', `${helperSource}\nreturn multisample`)
const sampleAgent = async (_prompt, { label }) => label === 'sample:fixture#1' ? null : { vote: label }
const sampleParallel = tasks => Promise.all(tasks.map(async task => {
  try { return await task() } catch { return null }
}))
const multisample = await loadMultisample(sampleAgent, sampleParallel)
const sampleNull = await multisample(index => `sample ${index}`, { n: 3, label: 'fixture' })
console.log(JSON.stringify({ scenario: 'multisample-null', output: sampleNull }))
assert.equal(sampleNull.status, 'INCOMPLETE')
assert.deepEqual(sampleNull.pending, ['sample:fixture#1'])
assert.deepEqual(sampleNull.samples.map(sample => sample.inputId), ['fixture#0', 'fixture#2'])
console.log('PASS: eight accounting controls; simulated runtime only')
