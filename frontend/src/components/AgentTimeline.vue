<script setup lang="ts">
import CommandResultCard from './CommandResultCard.vue'
import FileChangeCard from './FileChangeCard.vue'
import ToolEventCard from './ToolEventCard.vue'
import {
  isTruncatedPayload,
  type AgentEvent,
  type CommandFinishedEvent,
  type EventType,
  type FileChangedEvent,
  type ToolEvent,
} from '../types'

defineProps<{ events: AgentEvent[] }>()
const labels: Record<EventType, string> = {
  task_started: '任务启动', assistant_message: 'Agent 消息',
  tool_started: '调用工具', tool_finished: '工具结果',
  file_changed: '文件变化', command_finished: '命令结果',
  task_completed: '任务完成', task_failed: '任务未完成',
}

const isToolEvent = (event: AgentEvent): event is ToolEvent => (
  event.type === 'tool_started' || event.type === 'tool_finished'
)
const isFileEvent = (event: AgentEvent): event is FileChangedEvent => event.type === 'file_changed'
const isCommandEvent = (event: AgentEvent): event is CommandFinishedEvent => (
  event.type === 'command_finished'
)

function details(event: AgentEvent): string {
  if (isTruncatedPayload(event.payload)) {
    return `事件载荷已裁剪（原始 ${event.payload.original_characters} 字符）\n${event.payload.preview ?? ''}`
  }
  if (event.type === 'assistant_message') return event.payload.message
  if (event.type === 'task_started') return `运行模式：${event.payload.mode}`
  if (event.type === 'task_completed') return event.payload.result ?? '任务已完成'
  if (event.type === 'task_failed') {
    return event.payload.error
      ? `${event.payload.error.code} — ${event.payload.error.message}`
      : '任务失败，未提供错误详情'
  }
  return JSON.stringify(event.payload, null, 2)
}
</script>

<template>
  <div v-if="!events.length" class="empty-state">
    <span class="empty-mark" aria-hidden="true">&gt;_</span>
    <h3>从一个明确的任务开始</h3>
    <p>这里会展示 Agent 决策、工具调用、文件变化、命令结果和最终状态。</p>
  </div>
  <ol v-else class="timeline" aria-label="任务事件时间线">
    <li v-for="event in events" :key="event.id" class="event" :class="event.type">
      <div class="event-heading">
        <strong>{{ labels[event.type] || event.type }}</strong>
        <span class="event-context">
          <span v-if="event.step" class="step-label">step {{ event.step }}</span>
          <time :datetime="event.timestamp">{{ new Date(event.timestamp).toLocaleTimeString() }}</time>
        </span>
      </div>
      <ToolEventCard v-if="isToolEvent(event)" :event="event" />
      <FileChangeCard v-else-if="isFileEvent(event)" :event="event" />
      <CommandResultCard v-else-if="isCommandEvent(event)" :event="event" />
      <pre v-else>{{ details(event) }}</pre>
    </li>
  </ol>
</template>
