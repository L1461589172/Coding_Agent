import { isTruncatedPayload, type AgentEvent, type Task } from '../types'
import type {
  TaskRunViewModel,
  ThreadItem,
  ToolActivityThreadItem,
} from './types'

function payloadCallId(event: AgentEvent): string | undefined {
  if ('call_id' in event.payload && typeof event.payload.call_id === 'string') {
    return event.payload.call_id
  }
  return undefined
}

function payloadTool(event: AgentEvent): string | undefined {
  if ('tool' in event.payload && typeof event.payload.tool === 'string') {
    return event.payload.tool
  }
  return undefined
}

function activityState(activity: ToolActivityThreadItem): ToolActivityThreadItem['state'] {
  const finished = activity.finished?.payload
  if (finished && !isTruncatedPayload(finished)) {
    if (finished.cancelled === true) return 'cancelled'
    if (finished.ok === true) return 'success'
    if (finished.ok === false) return 'error'
  }
  const command = activity.command?.payload
  if (command && !isTruncatedPayload(command)) return command.ok ? 'success' : 'error'
  if (activity.fileChange && !isTruncatedPayload(activity.fileChange.payload)) return 'success'
  if (activity.started) return 'running'
  return 'unknown'
}

export function buildTaskRun(
  task: Task,
  events: AgentEvent[],
  eventWindowComplete = true,
): TaskRunViewModel {
  const items: ThreadItem[] = [{
    kind: 'user',
    key: `${task.id}:user`,
    prompt: task.prompt,
    timestamp: task.created_at,
  }]
  const activities = new Map<string, ToolActivityThreadItem>()
  const seenEventIds = new Set<string>()

  const activityFor = (event: AgentEvent): ToolActivityThreadItem => {
    const callId = payloadCallId(event) ?? `orphan-event-${event.id}`
    const key = `${task.id}:call:${callId}`
    let activity = activities.get(key)
    if (!activity) {
      activity = {
        kind: 'activity',
        key,
        taskId: task.id,
        callId,
        tool: payloadTool(event) ?? 'unknown_tool',
        state: 'unknown',
        timestamp: event.timestamp,
        step: event.step,
        rawEvents: [],
      }
      activities.set(key, activity)
      items.push(activity)
    }
    return activity
  }

  const orderedEvents = events.every((event, index) => (
    index === 0 || Number(events[index - 1].id) <= Number(event.id)
  ))
    ? events
    : [...events].sort((left, right) => Number(left.id) - Number(right.id))

  for (const event of orderedEvents) {
    if (event.task_id !== task.id) continue
    if (seenEventIds.has(event.id)) continue
    seenEventIds.add(event.id)
    if (event.type === 'assistant_message' && !isTruncatedPayload(event.payload)) {
      const message = event.payload.message.trim()
      if (!message) continue
      if (event.payload.mode === 'recovery' || event.payload.mode === 'scaffold') {
        items.push({
          kind: 'recovery',
          key: `${task.id}:event:${event.id}`,
          message,
          timestamp: event.timestamp,
          errorCode: event.payload.error_code,
        })
      } else {
        items.push({
          kind: 'agent',
          key: `${task.id}:event:${event.id}`,
          message,
          timestamp: event.timestamp,
          step: event.step,
        })
      }
      continue
    }
    if (event.type === 'tool_started' || event.type === 'tool_finished'
      || event.type === 'file_changed' || event.type === 'command_finished') {
      const activity = activityFor(event)
      activity.rawEvents.push(event)
      activity.tool = activity.tool === 'unknown_tool'
        ? (payloadTool(event) ?? activity.tool)
        : activity.tool
      if (event.type === 'tool_started') activity.started = event
      if (event.type === 'tool_finished') activity.finished = event
      if (event.type === 'file_changed') activity.fileChange = event
      if (event.type === 'command_finished') activity.command = event
      activity.state = activityState(activity)
    }
  }

  if (task.status === 'COMPLETED' || task.status === 'FAILED') {
    items.push({
      kind: 'terminal',
      key: `${task.id}:terminal`,
      status: task.status,
      timestamp: task.finished_at ?? task.created_at,
    })
  }

  return {
    taskId: task.id,
    status: task.status,
    createdAt: task.created_at,
    items,
    task,
    summary: task.summary,
    eventWindowComplete,
  }
}
