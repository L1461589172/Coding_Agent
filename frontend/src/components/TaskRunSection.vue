<script setup lang="ts">
import type { TaskRunViewModel } from '../thread/types'
import ActivityItem from './ActivityItem.vue'
import TaskSummaryCard from './TaskSummaryCard.vue'

defineProps<{ run: TaskRunViewModel }>()
</script>

<template>
  <section class="task-run" :aria-label="`任务 ${run.taskId.slice(0, 8)}`">
    <header class="task-run-header">
      <span>Task {{ run.taskId.slice(0, 8) }}</span>
      <span class="run-status" :class="run.status.toLowerCase()">{{ run.status }}</span>
    </header>
    <p v-if="!run.eventWindowComplete" class="history-window-note" role="status">
      较早的活动事件已过期；下方仍展示服务器保留窗口与完整终态 Summary。
    </p>
    <div class="thread-items">
      <template v-for="item in run.items" :key="item.key">
        <article v-if="item.kind === 'user'" class="message user-message">
          <div class="message-meta"><strong>你</strong><time :datetime="item.timestamp">{{ new Date(item.timestamp).toLocaleString() }}</time></div>
          <p>{{ item.prompt }}</p>
        </article>
        <article v-else-if="item.kind === 'agent'" class="message agent-message">
          <div class="message-meta"><strong>Agent</strong><span v-if="item.step">Step {{ item.step }}</span></div>
          <p>{{ item.message }}</p>
        </article>
        <article v-else-if="item.kind === 'recovery'" class="recovery-item" role="status">
          <strong>恢复提示<span v-if="item.errorCode"> · {{ item.errorCode }}</span></strong>
          <p>{{ item.message }}</p>
        </article>
        <ActivityItem v-else-if="item.kind === 'activity'" :activity="item" />
        <TaskSummaryCard v-else-if="item.kind === 'terminal'" :task="run.task" />
      </template>
    </div>
  </section>
</template>
