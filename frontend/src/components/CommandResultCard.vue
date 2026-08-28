<script setup lang="ts">
import { computed } from 'vue'
import {
  isTruncatedPayload,
  type CommandFinishedEvent,
  type CommandFinishedPayload,
  type TruncatedEventPayload,
} from '../types'

const props = defineProps<{ event: CommandFinishedEvent }>()
const truncatedPayload = computed<TruncatedEventPayload | null>(() => (
  isTruncatedPayload(props.event.payload) ? props.event.payload : null
))
const command = computed<CommandFinishedPayload | null>(() => (
  isTruncatedPayload(props.event.payload) ? null : props.event.payload
))
</script>

<template>
  <article class="event-card command-card">
    <template v-if="truncatedPayload">
      <div class="card-title"><code>command</code><span>载荷已裁剪</span></div>
      <p class="truncation-note">原始事件 {{ truncatedPayload.original_characters }} 字符。</p>
      <pre v-if="truncatedPayload.preview">{{ truncatedPayload.preview }}</pre>
    </template>
    <template v-else-if="command">
      <div class="card-title">
        <code class="command-line">$ {{ command.command }}</code>
        <span class="result-chip" :class="command.ok ? 'success' : 'failed'">
          {{ command.ok ? '通过' : '未通过' }}
        </span>
      </div>
      <p class="card-meta">
        exit {{ command.exit_code ?? '—' }} · {{ command.termination_reason }}
        · {{ command.duration_ms.toFixed(1) }} ms
        · 清理{{ command.cleanup_ok ? '完成' : '未确认' }}
      </p>
      <p v-if="command.error_code" class="tool-error"><code>{{ command.error_code }}</code></p>
      <details v-if="command.stdout" open>
        <summary>stdout <span v-if="command.stdout_truncated">（已截断）</span></summary>
        <pre class="terminal-output">{{ command.stdout }}</pre>
      </details>
      <details v-if="command.stderr" :open="!command.ok">
        <summary>stderr <span v-if="command.stderr_truncated">（已截断）</span></summary>
        <pre class="terminal-output stderr">{{ command.stderr }}</pre>
      </details>
    </template>
  </article>
</template>
