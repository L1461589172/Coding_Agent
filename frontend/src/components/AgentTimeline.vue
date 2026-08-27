<script setup lang="ts">
import type { AgentEvent, EventType } from '../types'
defineProps<{ events: AgentEvent[] }>()
const labels: Record<EventType, string> = {
  task_started: '任务启动', assistant_message: 'Runtime 消息',
  tool_started: '调用工具', tool_finished: '工具结果',
  file_changed: '文件变化', command_finished: '命令结果',
  task_completed: '任务完成', task_failed: '任务未完成',
}
function details(event: AgentEvent): string {
  const message = event.payload.message
  return typeof message === 'string' ? message : JSON.stringify(event.payload, null, 2)
}
</script>

<template>
  <div v-if="!events.length" class="empty-state">
    <span class="empty-mark" aria-hidden="true">&gt;_</span>
    <h3>从一个明确的任务开始</h3>
    <p>这里会展示 Runtime 事件。工具调用、文件变化和命令结果接入后，也将沿用同一条时间线。</p>
  </div>
  <ol v-else class="timeline" aria-label="任务事件时间线">
    <li v-for="event in events" :key="event.id" class="event" :class="event.type">
      <div class="event-heading">
        <strong>{{ labels[event.type] || event.type }}</strong>
        <time :datetime="event.timestamp">{{ new Date(event.timestamp).toLocaleTimeString() }}</time>
      </div>
      <pre>{{ details(event) }}</pre>
    </li>
  </ol>
</template>
