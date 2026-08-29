<script setup lang="ts">
import { computed } from 'vue'
import { formatToolActivity } from '../formatters/toolActivity'
import type { ToolActivityThreadItem } from '../thread/types'
import CommandDetails from './CommandDetails.vue'
import FileChangeDetails from './FileChangeDetails.vue'

const props = defineProps<{ activity: ToolActivityThreadItem }>()
const presentation = computed(() => formatToolActivity(props.activity))
const statusLabels = {
  running: '运行中', success: '成功', error: '失败', warning: '需注意',
}
</script>

<template>
  <article class="activity-item" :class="`activity-${presentation.status}`">
    <div class="activity-icon" aria-hidden="true">
      {{ presentation.status === 'running' ? '…' : presentation.status === 'success' ? '✓' : '!' }}
    </div>
    <div class="activity-body">
      <div class="activity-heading">
        <strong>{{ presentation.title }}</strong>
        <span class="activity-status">{{ statusLabels[presentation.status] }}</span>
      </div>
      <p v-if="presentation.detail" class="activity-detail">{{ presentation.detail }}</p>
      <FileChangeDetails v-if="activity.fileChange" :event="activity.fileChange" />
      <CommandDetails v-if="activity.command" :event="activity.command" />
    </div>
  </article>
</template>
