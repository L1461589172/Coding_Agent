import type {
  AgentEvent,
  CommandFinishedEvent,
  FileChangedEvent,
  Task,
  TaskSummary,
  ToolEvent,
} from '../types'

export interface UserThreadItem {
  kind: 'user'
  key: string
  prompt: string
  timestamp: string
}

export interface AgentThreadItem {
  kind: 'agent'
  key: string
  message: string
  timestamp: string
  step: number
}

export interface RecoveryThreadItem {
  kind: 'recovery'
  key: string
  message: string
  timestamp: string
  errorCode?: string
}

export type ActivityState = 'running' | 'success' | 'error' | 'cancelled' | 'unknown'

export interface ToolActivityThreadItem {
  kind: 'activity'
  key: string
  taskId: string
  callId: string
  tool: string
  state: ActivityState
  timestamp: string
  step: number
  started?: Extract<ToolEvent, { type: 'tool_started' }>
  finished?: Extract<ToolEvent, { type: 'tool_finished' }>
  fileChange?: FileChangedEvent
  command?: CommandFinishedEvent
  rawEvents: AgentEvent[]
}

export interface TerminalThreadItem {
  kind: 'terminal'
  key: string
  status: 'COMPLETED' | 'FAILED'
  timestamp: string
}

export type ThreadItem =
  | UserThreadItem
  | AgentThreadItem
  | RecoveryThreadItem
  | ToolActivityThreadItem
  | TerminalThreadItem

export interface TaskRunViewModel {
  taskId: string
  status: Task['status']
  createdAt: string
  items: ThreadItem[]
  task: Task
  summary: TaskSummary | null
  eventWindowComplete: boolean
}

export interface ConversationThreadViewModel {
  conversationId?: string
  runs: TaskRunViewModel[]
}

export type ComposerIntent = { kind: 'new_task', prompt: string }
