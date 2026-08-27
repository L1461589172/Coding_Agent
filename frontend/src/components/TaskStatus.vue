<script setup lang="ts">
import type { Task } from '../types'
defineProps<{ task: Task | null }>()
const labels = { PENDING: '等待启动', RUNNING: '运行中', COMPLETED: '已完成', FAILED: '未完成' }
</script>

<template>
  <section class="status-bar" aria-live="polite">
    <span class="status-pill" :class="task?.status.toLowerCase()">{{ task ? labels[task.status] : '就绪' }}</span>
    <span v-if="task" class="muted">任务 {{ task.id.slice(0, 8) }}</span>
    <span v-else class="muted">提交任务后，在下方查看执行事件</span>
  </section>
</template>
