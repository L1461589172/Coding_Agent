export type TaskStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface TaskError {
  code: string
  message: string
}

export interface CommandSummary {
  command: string
  ok: boolean
  exit_code: number | null
  timed_out: boolean
  cleanup_ok: boolean
  duration_ms: number | null
  error_code: string | null
}

export interface VerificationSummary {
  kind: 'pytest'
  command: string
  passed: boolean
  exit_code: number | null
  output_excerpt: string | null
  output_truncated: boolean
}

export interface TaskSummary {
  files_read: string[]
  files_changed: string[]
  commands: CommandSummary[]
  verification: VerificationSummary | null
  tool_calls: number
  decision_steps: number
  error_codes: string[]
  duration_ms: number | null
}

export interface Task {
  id: string
  session_id: string
  ordinal: number
  prompt: string
  status: TaskStatus
  mode: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  result: string | null
  error: TaskError | null
  summary: TaskSummary | null
}

export interface SessionListItem {
  id: string
  title: string
  created_at: string
  updated_at: string
  task_count: number
  last_task_id: string | null
  last_task_status: TaskStatus | null
  history_incomplete: boolean
}

export interface SessionPage {
  items: SessionListItem[]
  next_cursor: string | null
}

export interface TaskPage {
  items: Task[]
  next_before_ordinal: number | null
}

export interface ToolResultPayload {
  ok: boolean
  output: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  truncated: boolean
}

export interface TruncatedEventPayload {
  payload_truncated: true
  original_characters: number
  original_keys?: string[]
  preview?: string
  call_id?: string
  tool?: string
  ok?: boolean
  error_code?: string
  cancelled?: boolean
  path?: string
  action?: string
  exit_code?: number | null
  termination_reason?: string
}

export interface TaskStartedPayload { mode: string }

export interface AssistantMessagePayload {
  message: string
  mode: string
  tool_call_count?: number
  tool_names?: string[]
  error_code?: string
  consecutive_errors?: number
  max_consecutive_errors?: number
}

export interface ToolStartedPayload {
  call_id: string
  tool: string
  arguments: Record<string, unknown>
  synthetic: boolean
}

export interface ToolFinishedPayload {
  call_id: string
  tool: string
  ok?: boolean
  error_code?: string | null
  error_message?: string | null
  truncated?: boolean
  duration_ms: number
  result?: ToolResultPayload
  synthetic?: boolean
  cancelled?: boolean
  message?: string
}

export interface FileChangedPayload {
  call_id: string
  tool: string
  path: string
  action: string
  bytes_before: number
  bytes_after: number
  sha256_before: string | null
  sha256_after: string
  diff: string
  diff_truncated: boolean
  cleanup_pending: boolean
}

export interface CommandFinishedPayload {
  call_id: string
  ok: boolean
  error_code: string | null
  command: string
  exit_code: number | null
  termination_reason: string
  timed_out: boolean
  cleanup_ok: boolean
  stdout: string
  stderr: string
  stdout_truncated: boolean
  stderr_truncated: boolean
  duration_ms: number
}

export interface TaskCompletedPayload { result: string | null }
export interface TaskFailedPayload { error: TaskError | null }

export interface EventPayloads {
  task_started: TaskStartedPayload
  assistant_message: AssistantMessagePayload
  tool_started: ToolStartedPayload
  tool_finished: ToolFinishedPayload
  file_changed: FileChangedPayload
  command_finished: CommandFinishedPayload
  task_completed: TaskCompletedPayload
  task_failed: TaskFailedPayload
}

export type EventType = keyof EventPayloads

type EventOf<K extends EventType> = {
  id: string
  task_id: string
  type: K
  timestamp: string
  step: number
  payload: EventPayloads[K] | TruncatedEventPayload
}

export type AgentEvent = { [K in EventType]: EventOf<K> }[EventType]
export type ToolEvent = EventOf<'tool_started'> | EventOf<'tool_finished'>
export type FileChangedEvent = EventOf<'file_changed'>
export type CommandFinishedEvent = EventOf<'command_finished'>

export interface Metadata {
  workspace: string
  mode: string
  agent_ready: boolean
  tools: string[]
  tool_statuses: Record<string, 'ready' | 'not_implemented'>
}

const EVENT_TYPES = new Set<EventType>([
  'task_started', 'assistant_message', 'tool_started', 'tool_finished',
  'file_changed', 'command_finished', 'task_completed', 'task_failed',
])
const TASK_STATUSES = new Set<TaskStatus>(['PENDING', 'RUNNING', 'COMPLETED', 'FAILED'])

export const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
)
const isString = (value: unknown): value is string => typeof value === 'string'
const isNumber = (value: unknown): value is number => (
  typeof value === 'number' && Number.isFinite(value)
)
const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean'
const isNullableString = (value: unknown): value is string | null => (
  value === null || isString(value)
)
const isNullableNumber = (value: unknown): value is number | null => (
  value === null || isNumber(value)
)
const isOptionalString = (value: unknown): boolean => value === undefined || isString(value)
const isOptionalNumber = (value: unknown): boolean => value === undefined || isNumber(value)
const isOptionalStringArray = (value: unknown): boolean => (
  value === undefined || (Array.isArray(value) && value.every(isString))
)

export function isTruncatedPayload(value: unknown): value is TruncatedEventPayload {
  return isRecord(value) && value.payload_truncated === true && isNumber(value.original_characters)
}

function isTaskError(value: unknown): value is TaskError {
  return isRecord(value) && isString(value.code) && isString(value.message)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString)
}

function isCommandSummary(value: unknown): value is CommandSummary {
  return isRecord(value)
    && isString(value.command)
    && isBoolean(value.ok)
    && isNullableNumber(value.exit_code)
    && isBoolean(value.timed_out)
    && isBoolean(value.cleanup_ok)
    && isNullableNumber(value.duration_ms)
    && isNullableString(value.error_code)
}

function isVerificationSummary(value: unknown): value is VerificationSummary {
  return isRecord(value)
    && value.kind === 'pytest'
    && isString(value.command)
    && isBoolean(value.passed)
    && isNullableNumber(value.exit_code)
    && isNullableString(value.output_excerpt)
    && isBoolean(value.output_truncated)
}

function isTaskSummary(value: unknown): value is TaskSummary {
  return isRecord(value)
    && isStringArray(value.files_read)
    && isStringArray(value.files_changed)
    && Array.isArray(value.commands)
    && value.commands.every(isCommandSummary)
    && (value.verification === null || isVerificationSummary(value.verification))
    && isNumber(value.tool_calls)
    && Number.isInteger(value.tool_calls)
    && value.tool_calls >= 0
    && isNumber(value.decision_steps)
    && Number.isInteger(value.decision_steps)
    && value.decision_steps >= 0
    && isStringArray(value.error_codes)
    && isNullableNumber(value.duration_ms)
}

function isToolResult(value: unknown): value is ToolResultPayload {
  return isRecord(value)
    && isBoolean(value.ok)
    && isRecord(value.output)
    && isNullableString(value.error_code)
    && isNullableString(value.error_message)
    && isBoolean(value.truncated)
}

export function parseTask(value: unknown): Task {
  if (!isRecord(value)
    || !isString(value.id)
    || !isString(value.session_id)
    || !isNumber(value.ordinal)
    || !Number.isInteger(value.ordinal)
    || value.ordinal < 1
    || !isString(value.prompt)
    || !isString(value.status)
    || !TASK_STATUSES.has(value.status as TaskStatus)
    || !isString(value.mode)
    || !isString(value.created_at)
    || !isNullableString(value.started_at)
    || !isNullableString(value.finished_at)
    || !isNullableString(value.result)
    || !(value.error === null || isTaskError(value.error))
    || !(value.summary === null || isTaskSummary(value.summary))) {
    throw new Error('后端返回了无效的任务数据')
  }
  return value as unknown as Task
}

function isSession(value: unknown): value is SessionListItem {
  return isRecord(value)
    && isString(value.id)
    && isString(value.title)
    && isString(value.created_at)
    && isString(value.updated_at)
    && isNumber(value.task_count)
    && Number.isInteger(value.task_count)
    && value.task_count >= 0
    && isNullableString(value.last_task_id)
    && (value.last_task_status === null
      || (isString(value.last_task_status) && TASK_STATUSES.has(value.last_task_status as TaskStatus)))
    && isBoolean(value.history_incomplete)
}

export function parseSession(value: unknown): SessionListItem {
  if (!isSession(value)) throw new Error('后端返回了无效的会话数据')
  return value
}

export function parseSessionPage(value: unknown): SessionPage {
  if (!isRecord(value) || !Array.isArray(value.items) || !value.items.every(isSession)
    || !isNullableString(value.next_cursor)) {
    throw new Error('后端返回了无效的会话列表')
  }
  return value as unknown as SessionPage
}

export function parseTaskPage(value: unknown): TaskPage {
  if (!isRecord(value) || !Array.isArray(value.items)
    || !value.items.every((item) => {
      try { parseTask(item); return true } catch { return false }
    })
    || !(value.next_before_ordinal === null
      || (isNumber(value.next_before_ordinal) && Number.isInteger(value.next_before_ordinal)))) {
    throw new Error('后端返回了无效的任务列表')
  }
  return value as unknown as TaskPage
}

export function parseMetadata(value: unknown): Metadata {
  if (!isRecord(value)
    || !isString(value.workspace)
    || !isString(value.mode)
    || !isBoolean(value.agent_ready)
    || !Array.isArray(value.tools)
    || !value.tools.every(isString)
    || !isRecord(value.tool_statuses)
    || !Object.values(value.tool_statuses).every(
      (status) => status === 'ready' || status === 'not_implemented',
    )) {
    throw new Error('后端返回了无效的元数据')
  }
  return value as unknown as Metadata
}

function validPayload(type: EventType, value: unknown): boolean {
  if (isTruncatedPayload(value)) return true
  if (!isRecord(value)) return false
  switch (type) {
    case 'task_started':
      return isString(value.mode)
    case 'assistant_message':
      return isString(value.message) && isString(value.mode)
        && isOptionalNumber(value.tool_call_count)
        && isOptionalStringArray(value.tool_names)
        && isOptionalString(value.error_code)
        && isOptionalNumber(value.consecutive_errors)
        && isOptionalNumber(value.max_consecutive_errors)
    case 'tool_started':
      return isString(value.call_id) && isString(value.tool)
        && isRecord(value.arguments) && isBoolean(value.synthetic)
    case 'tool_finished':
      if (!isString(value.call_id) || !isString(value.tool) || !isNumber(value.duration_ms)) {
        return false
      }
      if (value.cancelled === true) return isString(value.message)
      return isBoolean(value.ok)
        && isNullableString(value.error_code)
        && isNullableString(value.error_message)
        && isBoolean(value.truncated)
        && isToolResult(value.result)
        && isBoolean(value.synthetic)
    case 'file_changed':
      return isString(value.call_id) && isString(value.tool) && isString(value.path)
        && isString(value.action) && isNumber(value.bytes_before) && isNumber(value.bytes_after)
        && isNullableString(value.sha256_before) && isString(value.sha256_after)
        && isString(value.diff) && isBoolean(value.diff_truncated)
        && isBoolean(value.cleanup_pending)
    case 'command_finished':
      return isString(value.call_id) && isBoolean(value.ok) && isNullableString(value.error_code)
        && isString(value.command) && isNullableNumber(value.exit_code)
        && isString(value.termination_reason) && isBoolean(value.timed_out)
        && isBoolean(value.cleanup_ok) && isString(value.stdout) && isString(value.stderr)
        && isBoolean(value.stdout_truncated) && isBoolean(value.stderr_truncated)
        && isNumber(value.duration_ms)
    case 'task_completed':
      return isNullableString(value.result)
    case 'task_failed':
      return value.error === null || isTaskError(value.error)
  }
}

export function parseAgentEvent(value: unknown, expectedTaskId: string): AgentEvent {
  if (!isRecord(value)
    || !isString(value.id)
    || !/^[1-9]\d*$/.test(value.id)
    || value.task_id !== expectedTaskId
    || !isString(value.type)
    || !EVENT_TYPES.has(value.type as EventType)
    || !isString(value.timestamp)
    || !Number.isFinite(Date.parse(value.timestamp))
    || !isNumber(value.step)
    || !Number.isInteger(value.step)
    || value.step < 0) {
    throw new Error('事件信封无效')
  }
  const type = value.type as EventType
  if (!validPayload(type, value.payload)) throw new Error(`事件 ${type} 的 payload 无效`)
  return value as AgentEvent
}
