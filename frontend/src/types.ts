export type TaskStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface Task {
  id: string
  prompt: string
  status: TaskStatus
  mode: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  result: string | null
  error: { code: string; message: string } | null
}

export type EventType = 'task_started' | 'assistant_message' | 'tool_started' | 'tool_finished'
  | 'file_changed' | 'command_finished' | 'task_completed' | 'task_failed'

export interface AgentEvent {
  id: string
  task_id: string
  type: EventType
  timestamp: string
  step: number
  payload: Record<string, unknown>
}

export interface Metadata {
  workspace: string
  mode: string
  agent_ready: boolean
  tools: string[]
  tool_statuses: Record<string, 'ready' | 'not_implemented'>
}
