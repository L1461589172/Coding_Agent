<script setup lang="ts">
import { isTruncatedPayload, type FileChangedEvent } from '../types'

defineProps<{ event: FileChangedEvent }>()
</script>

<template>
  <div v-if="isTruncatedPayload(event.payload)" class="truncation-note">
    文件变化详情已截断（原始 {{ event.payload.original_characters }} 字符）。
  </div>
  <details v-else class="activity-details">
    <summary>
      {{ event.payload.action === 'created' ? '新建文件' : '文件变更' }} · {{ event.payload.path }}
    </summary>
    <p v-if="event.payload.diff_truncated" class="truncation-note">Diff 已按工具输出上限截断。</p>
    <p v-if="event.payload.cleanup_pending" class="truncation-note">临时清理仍在等待完成。</p>
    <pre class="diff-output">{{ event.payload.diff || '文件内容未发生变化。' }}</pre>
  </details>
</template>
