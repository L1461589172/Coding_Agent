import { describe, expect, it } from 'vitest'
import type { AgentEvent } from '../types'
import type { ToolActivityThreadItem } from '../thread/types'
import { formatToolActivity, isPytestCommand } from './toolActivity'

function activity(tool: string, args: Record<string, unknown>): ToolActivityThreadItem {
  const started = {
    id: '1', task_id: 'task', type: 'tool_started', timestamp: '2026-08-29T00:00:00Z', step: 1,
    payload: { call_id: 'call', tool, arguments: args, synthetic: false },
  } as AgentEvent
  return {
    kind: 'activity', key: 'task:call:call', taskId: 'task', callId: 'call', tool,
    state: 'success', timestamp: started.timestamp, step: 1,
    started: started as Extract<AgentEvent, { type: 'tool_started' }>, rawEvents: [started],
  }
}

describe('formatToolActivity', () => {
  it.each([
    ['list_files', { path: '.' }, '查看了项目目录'],
    ['read_file', { path: 'README.md' }, '阅读了 README.md'],
    ['search_text', { query: 'needle' }, '搜索了“needle”'],
  ])('formats %s from structured arguments', (tool, args, expected) => {
    expect(formatToolActivity(activity(tool, args)).title).toBe(expected)
  })

  it.each([
    ['write_file', 'created', '创建了 src/a.ts'],
    ['replace_in_file', 'modified', '修改了 src/a.ts'],
  ])('uses file-change facts for %s success claims', (tool, action, expected) => {
    const item = activity(tool, { path: 'src/a.ts' })
    item.fileChange = {
      id: '2', task_id: 'task', type: 'file_changed', timestamp: item.timestamp, step: 1,
      payload: {
        call_id: 'call', tool, path: 'src/a.ts', action, bytes_before: 0, bytes_after: 1,
        sha256_before: null, sha256_after: 'a', diff: '+a', diff_truncated: false,
        cleanup_pending: false,
      },
    }
    expect(formatToolActivity(item).title).toBe(expected)
  })

  it('does not claim a file changed when no file-change fact exists', () => {
    const presentation = formatToolActivity(activity('write_file', { path: 'src/a.ts' }))
    expect(presentation.status).toBe('warning')
    expect(presentation.title).not.toContain('创建了')
    expect(presentation.title).not.toContain('更新了')
  })

  it('formats pytest only from an argv-equivalent command', () => {
    const item = activity('run_command', { command: 'python -m pytest -q' })
    expect(formatToolActivity(item).title).toBe('运行了测试')
    expect(isPytestCommand('echo pytest')).toBe(false)
    expect(isPytestCommand('python3 -m pytest tests')).toBe(true)
  })

  it('prioritizes structured errors and marks truncated facts', () => {
    const failed = activity('read_file', { path: 'secret.txt' })
    failed.state = 'error'
    failed.finished = {
      id: '2', task_id: 'task', type: 'tool_finished', timestamp: failed.timestamp, step: 1,
      payload: {
        call_id: 'call', tool: 'read_file', ok: false, error_code: 'PATH_NOT_ALLOWED',
        error_message: 'raw', truncated: false, duration_ms: 1,
        result: { ok: false, output: {}, error_code: 'PATH_NOT_ALLOWED', error_message: 'raw', truncated: false },
        synthetic: false,
      },
    }
    expect(formatToolActivity(failed).detail).toContain('PATH_NOT_ALLOWED')

    const truncated = activity('search_text', { query: 'x' })
    truncated.state = 'unknown'
    truncated.rawEvents = [{
      id: '3', task_id: 'task', type: 'tool_finished', timestamp: truncated.timestamp, step: 1,
      payload: { payload_truncated: true, original_characters: 9000, call_id: 'call', tool: 'search_text' },
    } as AgentEvent]
    expect(formatToolActivity(truncated)).toMatchObject({ status: 'warning', detail: '活动详情已截断。' })
  })
})
