<script setup lang="ts">
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
const normalItems = computed(() => {
  return props.run.items.filter(
    (item) =>
      item.kind !== 'activity',
  )
})


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
</script>


<template>
  <section
    class="task-run"
    :aria-label="`任务 ${run.taskId.slice(0, 8)}`"
  >
    <!-- ===================================================
         Task Header
         =================================================== -->

    <header class="task-run-header">
      <span>
        Task {{ run.taskId.slice(0, 8) }}
      </span>

      <span
        class="run-status"
        :class="run.status.toLowerCase()"
      >
        {{ run.status }}
      </span>
    </header>


    <!-- ===================================================
         History warning
         =================================================== -->

    <p
      v-if="!run.eventWindowComplete"
      class="history-window-note"
      role="status"
    >
      较早的活动事件已过期；
      当前仅展示服务器仍保留的执行记录，
      Task Summary 仍然完整。
    </p>


    <!-- ===================================================
         Main Conversation
         =================================================== -->

    <div class="thread-items">
      <template
        v-for="item in normalItems"
        :key="item.key"
      >
        <!-- User message -->
        <article
          v-if="item.kind === 'user'"
          class="message user-message"
        >
          <div class="message-meta">
            <strong>
              你
            </strong>

            <time
              :datetime="item.timestamp"
            >
              {{
                new Date(
                  item.timestamp,
                ).toLocaleString()
              }}
            </time>
          </div>

          <p>
            {{ item.prompt }}
          </p>
        </article>


        <!-- Agent message -->
        <article
          v-else-if="item.kind === 'agent'"
          class="message agent-message"
        >
          <div class="message-meta">
            <strong>
              Agent
            </strong>

            <span
              v-if="item.step"
            >
              Step {{ item.step }}
            </span>
          </div>

          <p>
            {{ item.message }}
          </p>
        </article>


        <!-- Recovery -->
        <article
          v-else-if="item.kind === 'recovery'"
          class="recovery-item"
          role="status"
        >
          <strong>
            恢复提示

            <span
              v-if="item.errorCode"
            >
              · {{ item.errorCode }}
            </span>
          </strong>

          <p>
            {{ item.message }}
          </p>
        </article>


        <!-- Terminal Summary -->
        <TaskSummaryCard
          v-else-if="item.kind === 'terminal'"
          :task="run.task"
        />
      </template>
    </div>


    <!-- ===================================================
         Activity Toggle
         =================================================== -->

    <button
      class="activity-toggle"
      type="button"
      :disabled="activityLoading"
      :aria-expanded="activityExpanded"
      @click="
        emit(
          'toggleActivity',
          run.task,
        )
      "
    >
      <span
        class="activity-toggle-icon"
        aria-hidden="true"
      >
        {{
          activityExpanded
            ? '⌄'
            : '›'
        }}
      </span>

      <span>
        {{ activityButtonText }}
      </span>
    </button>


    <!-- ===================================================
         Activity Details
         =================================================== -->

    <div
      v-if="activityExpanded"
      class="activity-panel"
    >
      <!-- 加载中 -->
      <div
        v-if="activityLoading"
        class="activity-loading"
        role="status"
      >
        <span
          class="activity-loading-dot"
          aria-hidden="true"
        >
          ●
        </span>

        正在加载执行记录…
      </div>


      <!-- 有 Activity -->
      <div
        v-else-if="activityItems.length"
        class="activity-list"
      >
        <ActivityItem
          v-for="activity in activityItems"
          :key="activity.key"
          :activity="activity"
        />
      </div>


      <!-- 已加载，但是没有可展示 Activity -->
      <div
        v-else-if="activityLoaded"
        class="activity-empty"
      >
        此任务没有可展示的工具执行记录。
      </div>


      <!--
        极短暂状态：
        已经要求展开，但是数据加载还没有正式开始。
      -->
      <div
        v-else
        class="activity-loading"
        role="status"
      >
        <span
          class="activity-loading-dot"
          aria-hidden="true"
        >
          ●
        </span>

        正在读取执行记录…
      </div>
    </div>
  </section>
</template>