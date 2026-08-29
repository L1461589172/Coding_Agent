<script setup lang="ts">
import { isTruncatedPayload, type CommandFinishedEvent } from '../types'

defineProps<{ event: CommandFinishedEvent }>()
</script>

<template>
  <div v-if="isTruncatedPayload(event.payload)" class="truncation-note">
    命令详情已截断（原始 {{ event.payload.original_characters }} 字符）。
  </div>
  <details v-else class="activity-details">
    <summary>
      <code>{{ event.payload.command }}</code>
      · exit {{ event.payload.exit_code ?? '—' }}
      · {{ Math.round(event.payload.duration_ms) }} ms
    </summary>
    <p v-if="event.payload.timed_out" class="tool-error">命令执行超时。</p>
    <p v-if="!event.payload.cleanup_ok" class="tool-error">命令进程清理未完全成功。</p>
    <p v-if="event.payload.stdout_truncated || event.payload.stderr_truncated" class="truncation-note">
      命令输出已按工具层上限截断。
    </p>
    <pre v-if="event.payload.stdout" class="terminal-output">{{ event.payload.stdout }}</pre>
    <pre v-if="event.payload.stderr" class="terminal-output stderr">{{ event.payload.stderr }}</pre>
  </details>
</template>
