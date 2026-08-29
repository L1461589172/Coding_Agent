const KEY = 'coding-agent:recent-context:v1'
const LEGACY_KEY = 'coding-agent:last-task-id'

export interface RecentContextV1 {
  version: 1
  taskId: string
}

function validTaskId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 128
}

export function loadRecentContext(storage: Storage = localStorage): RecentContextV1 | null {
  try {
    const raw = storage.getItem(KEY)
    if (raw) {
      const parsed: unknown = JSON.parse(raw)
      if (typeof parsed === 'object' && parsed !== null
        && 'version' in parsed && parsed.version === 1
        && 'taskId' in parsed && validTaskId(parsed.taskId)) {
        return { version: 1, taskId: parsed.taskId }
      }
      storage.removeItem(KEY)
    }
    const legacy = storage.getItem(LEGACY_KEY)
    if (validTaskId(legacy)) {
      const migrated = { version: 1 as const, taskId: legacy }
      storage.setItem(KEY, JSON.stringify(migrated))
      storage.removeItem(LEGACY_KEY)
      return migrated
    }
  } catch {
    return null
  }
  return null
}

export function saveRecentTask(taskId: string | null, storage: Storage = localStorage): void {
  try {
    if (taskId) storage.setItem(KEY, JSON.stringify({ version: 1, taskId }))
    else storage.removeItem(KEY)
    storage.removeItem(LEGACY_KEY)
  } catch { /* Browser storage is an optional recent-selection hint. */ }
}
