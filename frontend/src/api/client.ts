import {
  parseAgentEvent,
  parseMetadata,
  parseSession,
  parseSessionPage,
  parseTask,
  parseTaskPage,
  parseWorkspaceState,
  type AgentEvent,
  type Metadata,
  type SessionListItem,
  type SessionPage,
  type Task,
  type TaskPage,
  type WorkspaceState,
} from '../types'

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  url: string,
  parse: (value: unknown) => T,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(10000) })
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch { /* A stopped proxy can return a non-JSON error. */ }
    throw new ApiError(response.status, detail)
  }
  return parse(await response.json())
}

export const getMetadata = (): Promise<Metadata> => request('/api/meta', parseMetadata)
export const getWorkspaces = (): Promise<WorkspaceState> => request(
  '/api/workspaces',
  parseWorkspaceState,
)
export const switchWorkspace = (path: string): Promise<WorkspaceState> => request(
  '/api/workspaces/switch',
  parseWorkspaceState,
  { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) },
)
export const getTask = (id: string): Promise<Task> => request(
  `/api/tasks/${encodeURIComponent(id)}`,
  parseTask,
)
export const createTask = (prompt: string): Promise<Task> => request('/api/tasks', parseTask, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }),
})
export const getSessions = (before?: string): Promise<SessionPage> => request(
  `/api/sessions?limit=20${before ? `&before=${encodeURIComponent(before)}` : ''}`,
  parseSessionPage,
)
export const getSession = (id: string): Promise<SessionListItem> => request(
  `/api/sessions/${encodeURIComponent(id)}`,
  parseSession,
)
export const getSessionTasks = (id: string, before?: number): Promise<TaskPage> => request(
  `/api/sessions/${encodeURIComponent(id)}/tasks?limit=20${before ? `&before_ordinal=${before}` : ''}`,
  parseTaskPage,
)
export const createFollowUp = (id: string, prompt: string): Promise<Task> => request(
  `/api/sessions/${encodeURIComponent(id)}/tasks`,
  parseTask,
  { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }) },
)
export async function deleteSession(id: string): Promise<void> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
    method: 'DELETE', signal: AbortSignal.timeout(10000),
  })
  if (!response.ok) throw new ApiError(response.status, `删除失败（HTTP ${response.status}）`)
}

export interface WatchCallbacks {
  onEvent: (event: AgentEvent) => void
  onConnection: (connected: boolean) => void
  onHistoryReset: () => void
  onTaskMissing: () => void
  onError: (message: string) => void
  onEnd: () => void
}

const RETRY_DELAYS = [500, 1000, 2000, 4000, 8000, 15000]

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, milliseconds)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer)
      resolve()
    }, { once: true })
  })
}

function messages(buffer: string): { complete: string[], remainder: string } {
  const normalized = buffer.replaceAll('\r\n', '\n')
  const parts = normalized.split('\n\n')
  return { complete: parts.slice(0, -1), remainder: parts.at(-1) ?? '' }
}

function decodeEvent(block: string, id: string): AgentEvent | null {
  const data = block.split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
  if (!data) return null
  return parseAgentEvent(JSON.parse(data), id)
}

export function watchTask(
  id: string,
  after: string,
  callbacks: WatchCallbacks,
): () => void {
  const controller = new AbortController()
  let cursor = after
  let retries = 0

  async function run(): Promise<void> {
    while (!controller.signal.aborted) {
      try {
        const response = await fetch(
          `/api/tasks/${encodeURIComponent(id)}/events?after=${encodeURIComponent(cursor)}`,
          { headers: { Accept: 'text/event-stream' }, signal: controller.signal },
        )
        if (response.status === 204) {
          callbacks.onConnection(false)
          callbacks.onEnd()
          return
        }
        if (response.status === 404) {
          callbacks.onConnection(false)
          callbacks.onTaskMissing()
          return
        }
        if (response.status === 410) {
          callbacks.onConnection(false)
          callbacks.onHistoryReset()
          cursor = '0'
          retries = 0
          continue
        }
        if (!response.ok || !response.body) {
          if (response.status >= 400 && response.status < 500) {
            callbacks.onError(`事件流请求失败（HTTP ${response.status}）`)
            return
          }
          throw new Error(`Event stream HTTP ${response.status}`)
        }

        callbacks.onConnection(true)
        retries = 0
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read()
          buffer += decoder.decode(value, { stream: !done })
          const parsed = messages(buffer)
          buffer = parsed.remainder
          for (const block of parsed.complete) {
            const event = decodeEvent(block, id)
            if (!event || Number(event.id) <= Number(cursor)) continue
            cursor = event.id
            callbacks.onEvent(event)
          }
          if (done) break
        }
        callbacks.onConnection(false)
      } catch (cause) {
        callbacks.onConnection(false)
        if (controller.signal.aborted) return
        if (cause instanceof SyntaxError || (cause instanceof Error && cause.message.includes('事件'))) {
          callbacks.onError('事件流包含无效数据，已停止自动重连。')
          return
        }
      }
      const delay = RETRY_DELAYS[Math.min(retries, RETRY_DELAYS.length - 1)]
      retries += 1
      await wait(delay, controller.signal)
    }
  }

  void run()
  return () => controller.abort()
}
