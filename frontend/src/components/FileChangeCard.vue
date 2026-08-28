<script setup lang="ts">
import { computed } from 'vue'
import {
  isTruncatedPayload,
  type FileChangedEvent,
  type FileChangedPayload,
  type TruncatedEventPayload,
} from '../types'

const props = defineProps<{ event: FileChangedEvent }>()
const truncatedPayload = computed<TruncatedEventPayload | null>(() => (
  isTruncatedPayload(props.event.payload) ? props.event.payload : null
))
const change = computed<FileChangedPayload | null>(() => (
  isTruncatedPayload(props.event.payload) ? null : props.event.payload
))
</script>

<template>
  <article class="event-card file-card">
    <template v-if="truncatedPayload">
      <div class="card-title"><strong>{{ truncatedPayload.path || '文件变化' }}</strong><span>载荷已裁剪</span></div>
      <p class="truncation-note">原始事件 {{ truncatedPayload.original_characters }} 字符。</p>
      <pre v-if="truncatedPayload.preview">{{ truncatedPayload.preview }}</pre>
    </template>
    <template v-else-if="change">
      <div class="card-title">
        <strong>{{ change.path }}</strong>
        <span class="result-chip success">{{ change.action }}</span>
      </div>
      <p class="card-meta">
        {{ change.bytes_before }} → {{ change.bytes_after }} bytes
        · 调用 <code>{{ change.call_id }}</code>
      </p>
      <p v-if="change.cleanup_pending" class="tool-error">临时文件清理状态仍需确认</p>
      <pre class="diff-output">{{ change.diff || '文件内容未产生文本差异' }}</pre>
      <p v-if="change.diff_truncated" class="truncation-note">Diff 已按工具输出上限截断。</p>
    </template>
  </article>
</template>
