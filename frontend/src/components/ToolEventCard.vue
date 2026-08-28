<script setup lang="ts">
import { computed } from 'vue'
import {
  isTruncatedPayload,
  type ToolEvent,
  type ToolFinishedPayload,
  type ToolStartedPayload,
  type TruncatedEventPayload,
} from '../types'

const props = defineProps<{ event: ToolEvent }>()
const payload = computed(() => props.event.payload)
const truncatedPayload = computed<TruncatedEventPayload | null>(() => (
  isTruncatedPayload(props.event.payload) ? props.event.payload : null
))
const startedPayload = computed<ToolStartedPayload | null>(() => (
  props.event.type === 'tool_started' && !isTruncatedPayload(props.event.payload)
    ? props.event.payload
    : null
))
const finishedPayload = computed<ToolFinishedPayload | null>(() => (
  props.event.type === 'tool_finished' && !isTruncatedPayload(props.event.payload)
    ? props.event.payload
    : null
))
const status = computed(() => {
  if (truncatedPayload.value) return '载荷已裁剪'
  if (startedPayload.value) return startedPayload.value.synthetic ? '纠偏结果' : '执行中'
  if (finishedPayload.value?.cancelled) return '已取消'
  return finishedPayload.value?.ok ? '成功' : '失败'
})
</script>

<template>
  <article class="event-card tool-card">
    <div class="card-title">
      <code>{{ payload.tool || 'tool' }}</code>
      <span class="result-chip" :class="{ success: status === '成功', failed: status === '失败' }">
        {{ status }}
      </span>
    </div>
    <p v-if="payload.call_id" class="card-meta">调用 ID：<code>{{ payload.call_id }}</code></p>
    <template v-if="truncatedPayload">
      <p class="truncation-note">事件载荷超过上限，原始 {{ truncatedPayload.original_characters }} 字符。</p>
      <pre v-if="truncatedPayload.preview">{{ truncatedPayload.preview }}</pre>
    </template>
    <template v-else-if="startedPayload">
      <details open>
        <summary>调用参数</summary>
        <pre>{{ JSON.stringify(startedPayload.arguments, null, 2) }}</pre>
      </details>
    </template>
    <template v-else-if="finishedPayload">
      <p class="card-meta">
        耗时 {{ finishedPayload.duration_ms.toFixed(1) }} ms
        <span v-if="finishedPayload.truncated"> · 工具输出已截断</span>
      </p>
      <p v-if="finishedPayload.error_code" class="tool-error">
        <code>{{ finishedPayload.error_code }}</code>
        <span v-if="finishedPayload.error_message"> — {{ finishedPayload.error_message }}</span>
      </p>
      <p v-if="finishedPayload.message">{{ finishedPayload.message }}</p>
      <details v-if="finishedPayload.result" :open="!finishedPayload.ok">
        <summary>结构化结果</summary>
        <pre>{{ JSON.stringify(finishedPayload.result, null, 2) }}</pre>
      </details>
    </template>
  </article>
</template>
