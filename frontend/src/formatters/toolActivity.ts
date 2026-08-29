import { isRecord, isTruncatedPayload } from '../types'
import type { ActivityState, ToolActivityThreadItem } from '../thread/types'

export interface ActivityPresentation {
  title: string
  detail?: string
  status: 'running' | 'success' | 'error' | 'warning'
}

const ERROR_LABELS: Record<string, string> = {
  PATH_NOT_ALLOWED: '路径不在允许的工作区范围内',
  FILE_NOT_FOUND: '目标文件不存在',
  COMMAND_NOT_ALLOWED: '命令不在本地允许列表中',
  COMMAND_TIMEOUT: '命令执行超时',
  COMMAND_FAILED: '命令返回了失败状态',
  REPEATED_TOOL_CALL: 'Agent 重复了相同工具调用',
  INVALID_ARGUMENTS: '工具参数无效',
}

function argument(activity: ToolActivityThreadItem, name: string): unknown {
  const payload = activity.started?.payload
  if (!payload || isTruncatedPayload(payload) || !isRecord(payload.arguments)) return undefined
  return payload.arguments[name]
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function stateStatus(state: ActivityState): ActivityPresentation['status'] {
  if (state === 'error') return 'error'
  if (state === 'cancelled' || state === 'unknown') return 'warning'
  return state
}

function stateVerb(activity: ToolActivityThreadItem, success: string, running: string): string {
  if (activity.state === 'running') return running
  if (activity.state === 'error') return `${success}时失败`
  if (activity.state === 'cancelled') return `${success}被取消`
  if (activity.state === 'unknown') return `${success}（状态不完整）`
  return success
}

function errorDetail(activity: ToolActivityThreadItem): string | undefined {
  const payload = activity.finished?.payload
  if (!payload) return undefined
  if (isTruncatedPayload(payload)) return '活动详情已截断，无法确认完整工具结果。'
  if (payload.cancelled) return payload.message
  if (!payload.error_code) return payload.error_message ?? undefined
  return ERROR_LABELS[payload.error_code]
    ? `${ERROR_LABELS[payload.error_code]}（${payload.error_code}）`
    : `${payload.error_code}${payload.error_message ? ` — ${payload.error_message}` : ''}`
}

function resultOutputText(activity: ToolActivityThreadItem, name: string): string | undefined {
  const payload = activity.finished?.payload
  if (!payload || isTruncatedPayload(payload) || !payload.result?.ok) return undefined
  return text(payload.result.output[name])
}

export function isPytestCommand(command: string): boolean {
  const normalized = command.trim().replaceAll(/\s+/g, ' ').toLowerCase()
  return normalized === 'pytest'
    || normalized.startsWith('pytest ')
    || normalized === 'python -m pytest'
    || normalized.startsWith('python -m pytest ')
    || normalized === 'python3 -m pytest'
    || normalized.startsWith('python3 -m pytest ')
}

export function formatToolActivity(activity: ToolActivityThreadItem): ActivityPresentation {
  const path = resultOutputText(activity, 'path') ?? text(argument(activity, 'path'))
  const query = text(argument(activity, 'query'))
  const commandPayload = activity.command?.payload
  const command = commandPayload && !isTruncatedPayload(commandPayload)
    ? commandPayload.command
    : text(argument(activity, 'command'))
  const filePayload = activity.fileChange?.payload
  const changedPath = filePayload && !isTruncatedPayload(filePayload)
    ? filePayload.path
    : path
  let title: string

  switch (activity.tool) {
    case 'list_files':
      title = stateVerb(
        activity,
        path && path !== '.' ? `查看了 ${path} 目录` : '查看了项目目录',
        path && path !== '.' ? `正在查看 ${path} 目录` : '正在查看项目目录',
      )
      break
    case 'read_file':
      title = stateVerb(
        activity,
        `阅读了 ${path ?? '一个文件'}`,
        `正在阅读 ${path ?? '文件'}`,
      )
      break
    case 'search_text':
      title = stateVerb(
        activity,
        `搜索了${query ? `“${query}”` : '项目文本'}`,
        `正在搜索${query ? `“${query}”` : '项目文本'}`,
      )
      break
    case 'write_file': {
      const action = filePayload && !isTruncatedPayload(filePayload) ? filePayload.action : undefined
      if (activity.state === 'success' && !action) {
        return {
          title: `写入工具已完成：${path ?? '文件'}`,
          detail: '未收到文件变更事实，无法确认文件已被创建或更新。',
          status: 'warning',
        }
      }
      const success = action === 'created'
        ? `创建了 ${changedPath ?? '文件'}`
        : `更新了 ${changedPath ?? '文件'}`
      title = stateVerb(activity, success, `正在写入 ${path ?? '文件'}`)
      break
    }
    case 'replace_in_file':
      if (activity.state === 'success'
        && (!filePayload || isTruncatedPayload(filePayload))) {
        return {
          title: `替换工具已完成：${path ?? '文件'}`,
          detail: '未收到文件变更事实，无法确认文件已被修改。',
          status: 'warning',
        }
      }
      title = stateVerb(
        activity,
        `修改了 ${changedPath ?? '文件'}`,
        `正在修改 ${path ?? '文件'}`,
      )
      break
    case 'run_command':
      title = stateVerb(
        activity,
        command && isPytestCommand(command) ? '运行了测试' : '执行了命令',
        command && isPytestCommand(command) ? '正在运行测试' : '正在执行命令',
      )
      break
    default:
      title = stateVerb(
        activity,
        `调用了 ${activity.tool}`,
        `正在调用 ${activity.tool}`,
      )
  }

  const truncated = activity.rawEvents.some((event) => isTruncatedPayload(event.payload))
  return {
    title,
    detail: errorDetail(activity) ?? (truncated ? '活动详情已截断。' : undefined),
    status: stateStatus(activity.state),
  }
}
