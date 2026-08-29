import { describe, expect, it } from 'vitest'
import type { AgentEvent, Task } from '../types'
import { buildConversationThread } from './buildConversationThread'
import { buildTaskRun } from './buildTaskRun'

const timestamp = '2026-08-29T08:00:00Z'

function task(id: string, status: Task['status'] = 'RUNNING'): Task {
  return {
    id,
    session_id: '00000000-0000-4000-8000-000000000001',
    ordinal: 1,
    prompt: `prompt-${id}`,
    status,
    mode: 'agent',
    created_at: timestamp,
    started_at: timestamp,
    finished_at: status === 'RUNNING' ? null : timestamp,
    result: status === 'COMPLETED' ? 'done' : null,
    error: status === 'FAILED' ? { code: 'FAILED', message: 'failed' } : null,
    summary: null,
  }
}

function event(
  taskId: string,
  id: number,
  type: AgentEvent['type'],
  payload: Record<string, unknown>,
): AgentEvent {
  return { id: String(id), task_id: taskId, type, timestamp, step: id, payload } as unknown as AgentEvent
}

function started(taskId: string, id = 2, callId = 'same-call'): AgentEvent {
  return event(taskId, id, 'tool_started', {
    call_id: callId,
    tool: 'write_file',
    arguments: { path: 'src/a.ts' },
    synthetic: false,
  })
}

function finished(taskId: string, id = 4, callId = 'same-call'): AgentEvent {
  return event(taskId, id, 'tool_finished', {
    call_id: callId,
    tool: 'write_file',
    ok: true,
    error_code: null,
    error_message: null,
    truncated: false,
    duration_ms: 3,
    result: { ok: true, output: {}, error_code: null, error_message: null, truncated: false },
    synthetic: false,
  })
}

function changed(taskId: string, id = 3, callId = 'same-call'): AgentEvent {
  return event(taskId, id, 'file_changed', {
    call_id: callId,
    tool: 'write_file',
    path: 'src/a.ts',
    action: 'created',
    bytes_before: 0,
    bytes_after: 3,
    sha256_before: null,
    sha256_after: 'abc',
    diff: '+ok',
    diff_truncated: false,
    cleanup_pending: false,
  })
}

describe('buildTaskRun', () => {
  it('orders numeric IDs and aggregates a lifecycle and file attachment by call ID', () => {
    const run = buildTaskRun(task('task-a'), [finished('task-a'), changed('task-a'), started('task-a')])
    const activities = run.items.filter((item) => item.kind === 'activity')

    expect(activities).toHaveLength(1)
    expect(activities[0]).toMatchObject({
      key: 'task-a:call:same-call',
      state: 'success',
      tool: 'write_file',
    })
    expect(activities[0].rawEvents.map((item) => item.id)).toEqual(['2', '3', '4'])
    expect(activities[0].fileChange?.payload).toMatchObject({ path: 'src/a.ts' })
  })

  it('ignores duplicate event IDs, empty messages, and events from another task', () => {
    const blank = event('task-a', 1, 'assistant_message', { message: '  ', mode: 'agent' })
    const message = event('task-a', 5, 'assistant_message', { message: 'result', mode: 'agent' })
    const run = buildTaskRun(task('task-a'), [blank, started('task-a'), started('task-a'), message, started('task-b')])

    expect(run.items.filter((item) => item.kind === 'activity')).toHaveLength(1)
    expect(run.items.filter((item) => item.kind === 'agent')).toHaveLength(1)
  })

  it('keeps recovery, incomplete-window and truncated orphan facts explicit', () => {
    const recovery = event('task-a', 1, 'assistant_message', {
      message: 'retrying',
      mode: 'recovery',
      error_code: 'LLM_TIMEOUT',
    })
    const orphan = event('task-a', 2, 'tool_finished', {
      payload_truncated: true,
      original_characters: 9000,
      call_id: 'orphan',
      tool: 'read_file',
    })
    const run = buildTaskRun(task('task-a'), [recovery, orphan], false)

    expect(run.eventWindowComplete).toBe(false)
    expect(run.items.find((item) => item.kind === 'recovery')).toMatchObject({
      errorCode: 'LLM_TIMEOUT',
    })
    expect(run.items.find((item) => item.kind === 'activity')).toMatchObject({
      key: 'task-a:call:orphan',
      state: 'unknown',
    })
  })

  it('scopes identical event and call IDs to each task when composing runs', () => {
    const first = buildTaskRun(task('task-a'), [started('task-a')])
    const second = buildTaskRun(task('task-b'), [started('task-b')])
    const thread = buildConversationThread([first, second])
    const keys = thread.runs.map((run) => run.items.find((item) => item.kind === 'activity')?.key)

    expect(keys).toEqual(['task-a:call:same-call', 'task-b:call:same-call'])
  })

  it('handles more than the retained 512-event window without losing stable activities', () => {
    const events = Array.from({ length: 600 }, (_, index) => event('task-a', index + 1, 'tool_started', {
      call_id: `call-${index}`,
      tool: 'read_file',
      arguments: { path: `very/long/path/${index}/file.ts` },
      synthetic: false,
    }))
    const run = buildTaskRun(task('task-a'), events)

    expect(run.items.filter((item) => item.kind === 'activity')).toHaveLength(600)
    expect(run.items.at(-1)?.key).toBe('task-a:call:call-599')
  })
})
