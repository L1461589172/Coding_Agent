<script setup lang="ts">
import type { ConversationThreadViewModel } from '../thread/types'
import TaskRunSection from './TaskRunSection.vue'

defineProps<{ thread: ConversationThreadViewModel }>()
</script>

<template>
  <section class="conversation-thread" aria-label="任务线程">
    <div v-if="!thread.runs.length" class="thread-empty">
      <span aria-hidden="true">&gt;_</span>
      <h2>准备好开始一个任务</h2>
      <p>提交后，这里会按顺序展示 Agent 消息、聚合工具活动、真实文件变更、命令结果与终态事实。</p>
    </div>
    <TaskRunSection v-for="run in thread.runs" :key="run.taskId" :run="run" />
  </section>
</template>
