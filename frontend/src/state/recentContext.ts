const KEY = 'coding-agent:recent-context:v2'
const V1_KEY = 'coding-agent:recent-context:v1'
const LEGACY_KEY = 'coding-agent:last-task-id'

export interface RecentContextV2 {
  version: 2
  sessionId: string
  taskId?: string
}

function validTaskId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 128
}

export function loadRecentContext(storage: Storage = localStorage): RecentContextV2 | { version: 1, taskId: string } | null {
  try {
    const raw = storage.getItem(KEY)
    if (raw) {
      const parsed: unknown = JSON.parse(raw)
      if (typeof parsed === 'object' && parsed !== null
        && 'version' in parsed && parsed.version === 2
        && 'sessionId' in parsed && validTaskId(parsed.sessionId)) {
        return {
          version: 2,
          sessionId: parsed.sessionId,
          ...('taskId' in parsed && validTaskId(parsed.taskId) ? { taskId: parsed.taskId } : {}),
        }
      }
      storage.removeItem(KEY)
    }
    const v1 = storage.getItem(V1_KEY)
    if (v1) {
      const parsed: unknown = JSON.parse(v1)
      if (typeof parsed === 'object' && parsed !== null && 'taskId' in parsed
        && validTaskId(parsed.taskId)) return { version: 1, taskId: parsed.taskId }
      storage.removeItem(V1_KEY)
    }
    const legacy = storage.getItem(LEGACY_KEY)
    if (validTaskId(legacy)) {
      storage.removeItem(LEGACY_KEY)
      storage.setItem(V1_KEY, JSON.stringify({ version: 1, taskId: legacy }))
      return { version: 1, taskId: legacy }
    }
  } catch {
    return null
  }
  return null
}

export function saveRecentContext(
  sessionId: string | null,
  taskId?: string,
  storage: Storage = localStorage,
): void {
  try {
    if (sessionId) storage.setItem(KEY, JSON.stringify({ version: 2, sessionId, taskId }))
    else storage.removeItem(KEY)
    storage.removeItem(V1_KEY)
    storage.removeItem(LEGACY_KEY)
  } catch { /* Browser storage is an optional recent-selection hint. */ }
}

export function saveRecentTask(taskId: string | null, storage: Storage = localStorage): void {
  try {
    if (taskId) storage.setItem(V1_KEY, JSON.stringify({ version: 1, taskId }))
    else saveRecentContext(null, undefined, storage)
  } catch { /* Browser storage is an optional recent-selection hint. */ }
}
