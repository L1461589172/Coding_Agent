import type { AgentEvent, Metadata, Task } from '../types'

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(10000) })
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch { /* A stopped proxy can return a non-JSON error. */ }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const getMetadata = () => request<Metadata>('/api/meta')
export const getTask = (id: string) => request<Task>(`/api/tasks/${encodeURIComponent(id)}`)
export const createTask = (prompt: string) => request<Task>('/api/tasks', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }),
})

export function watchTask(
  id: string,
  after: string,
  onEvent: (event: AgentEvent) => void,
  onConnection: (connected: boolean) => void,
): () => void {
  const stream = new EventSource(`/api/tasks/${encodeURIComponent(id)}/events?after=${after}`)
  stream.onopen = () => onConnection(true)
  stream.onerror = () => onConnection(false)
  stream.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as AgentEvent
      if (event.task_id !== id || !event.id || !event.type) throw new Error('Invalid event')
      onEvent(event)
    } catch {
      stream.close()
      onConnection(false)
    }
  }
  return () => stream.close()
}
