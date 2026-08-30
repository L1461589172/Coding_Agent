<script setup lang="ts">
import {
  PhCaretDown,
  PhCaretRight,
  PhCircleNotch,
  PhRobot,
} from '@phosphor-icons/vue'
import { computed } from 'vue'

import type {
  TaskRunViewModel,
  ToolActivityThreadItem,
} from '../thread/types'

import ActivityItem from './ActivityItem.vue'
import TaskSummaryCard from './TaskSummaryCard.vue'


/* =========================================================
   Props
   ========================================================= */

const props = withDefaults(
  defineProps<{
    run: TaskRunViewModel

    /*
     * 是否正在从后端加载历史 Activity。
     */
    activityLoading?: boolean

    /*
     * 是否已经加载过 Activity。
     */
    activityLoaded?: boolean

    /*
     * 执行详情当前是否展开。
     */
    activityExpanded?: boolean
  }>(),
  {
    activityLoading: false,
    activityLoaded: false,
    activityExpanded: false,
  },
)


/* =========================================================
   Emits
   ========================================================= */

const emit = defineEmits<{
  toggleActivity: [
    task: TaskRunViewModel['task'],
  ]
}>()


/* =========================================================
   Separate Activity from main conversation
   ========================================================= */

/*
 * Activity 不再直接混在普通消息流中渲染。
 *
 * 原因：
 *
 * buildTaskRun() 会按照真实事件时间，
 * 把 Activity 放在 run.items 的中间。
 *
 * 如果“查看执行详情”按钮位于 Task 底部，
 * 用户点击以后 Activity 会突然出现在按钮上方，
 * 很容易让用户误以为没有展开。
 *
 * 所以这里把：
 *
 *   Activity
 *
 * 和：
 *
 *   User
 *   Agent
 *   Recovery
 *   Terminal Summary
 *
 * 分开。
 */


/*
 * 普通对话区域。
 */
const userItem = computed(() => props.run.items.find((item) => item.kind === 'user'))

const responseItems = computed(() => props.run.items.filter(
  (item) => item.kind === 'agent' || item.kind === 'recovery',
))

const terminalItem = computed(() => props.run.items.find((item) => item.kind === 'terminal'))


/*
 * 独立的执行详情。
 */
const activityItems = computed(() => {
  return props.run.items.filter(
    (
      item,
    ): item is ToolActivityThreadItem =>
      item.kind === 'activity',
  )
})


const activityCount = computed(() => {
  return activityItems.value.length
})


/* =========================================================
   Activity button
   ========================================================= */

const activityButtonText = computed(() => {
  if (props.activityLoading) {
    return '正在加载执行详情…'
  }

  if (props.activityExpanded) {
    return '收起执行详情'
  }

  if (
    props.activityLoaded &&
    activityCount.value > 0
  ) {
    return `查看执行详情 · ${activityCount.value}`
  }

  return '查看执行详情'
})

function shortTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
</script>


<template>
  <section class="task-run" :aria-label="`任务 ${run.taskId.slice(0, 8)}`">
    <article v-if="userItem?.kind === 'user'" class="user-turn">
      <div class="user-message">
        <time :datetime="userItem.timestamp">{{ shortTime(userItem.timestamp) }}</time>
        <p>{{ userItem.prompt }}</p>
      </div>
      <span class="user-avatar" aria-label="你">你</span>
    </article>

    <article class="agent-turn">
      <span class="agent-avatar" aria-hidden="true">
        <PhRobot :size="21" weight="duotone" />
      </span>

      <div class="agent-response">
        <header class="agent-response-heading">
          <strong>Coding Agent</strong>
          <time :datetime="run.createdAt">{{ shortTime(run.createdAt) }}</time>
        </header>

        <p v-if="!run.eventWindowComplete" class="history-window-note" role="status">
          较早的活动事件已过期；当前展示服务器仍保留的执行记录，任务总结仍然完整。
        </p>

        <div v-if="responseItems.length" class="agent-copy">
          <template v-for="item in responseItems" :key="item.key">
            <p v-if="item.kind === 'agent'">{{ item.message }}</p>
            <div v-else class="recovery-item" role="status">
              <strong>恢复提示<span v-if="item.errorCode"> · {{ item.errorCode }}</span></strong>
              <p>{{ item.message }}</p>
            </div>
          </template>
        </div>

        <button
          class="activity-toggle"
          type="button"
          :disabled="activityLoading"
          :aria-expanded="activityExpanded"
          @click="emit('toggleActivity', run.task)"
        >
          <PhCaretDown v-if="activityExpanded" :size="15" weight="bold" aria-hidden="true" />
          <PhCaretRight v-else :size="15" weight="bold" aria-hidden="true" />
          <span>{{ activityButtonText }}</span>
        </button>

        <div v-if="activityExpanded" class="activity-panel">
          <div v-if="activityLoading" class="activity-loading" role="status">
            <PhCircleNotch :size="16" aria-hidden="true" />
            正在加载执行记录…
          </div>

          <div v-else-if="activityItems.length" class="activity-list">
            <ActivityItem
              v-for="activity in activityItems"
              :key="activity.key"
              :activity="activity"
            />
          </div>

          <div v-else-if="activityLoaded" class="activity-empty">
            此任务没有可展示的工具执行记录。
          </div>

          <div v-else class="activity-loading" role="status">
            <PhCircleNotch :size="16" aria-hidden="true" />
            正在读取执行记录…
          </div>
        </div>

        <TaskSummaryCard v-if="terminalItem" :task="run.task" />
      </div>
    </article>
  </section>
</template>
