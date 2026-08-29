<script setup lang="ts">
import type {
  ConversationThreadViewModel,
} from '../thread/types'

import type {
  Task,
} from '../types'

import TaskRunSection
  from './TaskRunSection.vue'


defineProps<{
  thread: ConversationThreadViewModel

  /*
   * 下面三个 Set 由 AppM6 管理，
   * ConversationThread 只负责向下传递。
   */
  loadingActivity: Set<string>
  loadedActivity: Set<string>
  expandedActivity: Set<string>
}>()


const emit = defineEmits<{
  /*
   * TaskRunSection 点击
   * “查看 / 收起执行详情”
   * 后逐层通知 AppM6。
   */
  toggleActivity: [task: Task]
}>()
</script>


<template>
  <section
    class="conversation-thread"
    aria-label="任务线程"
  >
    <!-- 空会话 -->
    <div
      v-if="!thread.runs.length"
      class="thread-empty"
    >
      <span aria-hidden="true">
        &gt;_
      </span>

      <h2>
        准备好开始一个任务
      </h2>

      <p>
        提交后，这里会按顺序展示
        Agent 消息、真实文件变更、
        命令结果与任务总结。
      </p>
    </div>


    <!-- Task Runs -->
    <TaskRunSection
      v-for="run in thread.runs"
      :key="run.taskId"
      :run="run"

      :activity-loading="
        loadingActivity.has(
          run.taskId,
        )
      "

      :activity-loaded="
        loadedActivity.has(
          run.taskId,
        )
      "

      :activity-expanded="
        expandedActivity.has(
          run.taskId,
        )
      "

      @toggle-activity="
        emit(
          'toggleActivity',
          $event,
        )
      "
    />
  </section>
</template>