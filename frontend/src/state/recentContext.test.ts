import { describe, expect, it } from 'vitest'
import { loadRecentContext, saveRecentTask } from './recentContext'

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() { return this.values.size }
  clear() { this.values.clear() }
  getItem(key: string) { return this.values.get(key) ?? null }
  key(index: number) { return [...this.values.keys()][index] ?? null }
  removeItem(key: string) { this.values.delete(key) }
  setItem(key: string, value: string) { this.values.set(key, value) }
}

describe('recent context storage', () => {
  it('round-trips v1 state and clears it', () => {
    const storage = new MemoryStorage()
    saveRecentTask('task-a', storage)
    expect(loadRecentContext(storage)).toEqual({ version: 1, taskId: 'task-a' })
    saveRecentTask(null, storage)
    expect(loadRecentContext(storage)).toBeNull()
  })

  it('migrates the legacy task key', () => {
    const storage = new MemoryStorage()
    storage.setItem('coding-agent:last-task-id', 'legacy-task')
    expect(loadRecentContext(storage)).toEqual({ version: 1, taskId: 'legacy-task' })
    expect(storage.getItem('coding-agent:last-task-id')).toBeNull()
    expect(storage.getItem('coding-agent:recent-context:v1')).toContain('legacy-task')
  })

  it('removes damaged versioned state without throwing', () => {
    const storage = new MemoryStorage()
    storage.setItem('coding-agent:recent-context:v1', '{bad json')
    expect(loadRecentContext(storage)).toBeNull()
  })
})
