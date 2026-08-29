import { describe, expect, it } from 'vitest'
import { parseTask } from './types'

function payload() {
  return {
    id: 'task', session_id: 'session', ordinal: 1,
    prompt: 'work', status: 'COMPLETED', mode: 'agent',
    created_at: '2026-08-29T00:00:00Z', started_at: '2026-08-29T00:00:00Z',
    finished_at: '2026-08-29T00:00:01Z', result: 'done', error: null,
    summary: {
      files_read: ['README.md'], files_changed: ['src/a.ts'],
      commands: [{ command: 'pytest -q', ok: true, exit_code: 0, timed_out: false, cleanup_ok: true, duration_ms: 12, error_code: null }],
      verification: { kind: 'pytest', command: 'pytest -q', passed: true, exit_code: 0, output_excerpt: '1 passed', output_truncated: false },
      tool_calls: 2, decision_steps: 1, error_codes: [], duration_ms: 1000,
    },
  }
}

describe('parseTask summary contract', () => {
  it('accepts a complete terminal summary', () => {
    expect(parseTask(payload()).summary?.verification?.passed).toBe(true)
  })

  it.each([
    ['negative count', (value: ReturnType<typeof payload>) => { value.summary.tool_calls = -1 }],
    ['invalid command', (value: ReturnType<typeof payload>) => { value.summary.commands[0].cleanup_ok = 'yes' as never }],
    ['invalid verification', (value: ReturnType<typeof payload>) => { value.summary.verification.kind = 'jest' as never }],
  ])('rejects %s in a nested summary', (_name, mutate) => {
    const value = payload()
    mutate(value)
    expect(() => parseTask(value)).toThrow('无效的任务数据')
  })
})
