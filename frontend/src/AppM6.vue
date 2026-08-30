<script setup lang="ts">
import { PhCaretDown } from '@phosphor-icons/vue'
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
} from 'vue'

import {
  ApiError,
  createFollowUp,
  createTask,
  getMetadata,
  getSessionTasks,
  getSessions,
  getTask,
  getWorkspaces,
  switchWorkspace,
  watchTask,
} from './api/client'

import ConversationThread from './components/ConversationThread.vue'
import Sidebar from './components/Sidebar.vue'
import TaskComposer from './components/TaskComposer.vue'

import {
  loadRecentContext,
  saveRecentContext,
} from './state/recentContext'

import {
  buildConversationThread,
} from './thread/buildConversationThread'

import {
  buildTaskRun,
} from './thread/buildTaskRun'

import type {
  ComposerIntent,
} from './thread/types'

import type {
  AgentEvent,
  Metadata,
  SessionListItem,
  Task,
  WorkspaceState,
} from './types'


/* =========================================================
   State
   ========================================================= */

const metadata = ref<Metadata | null>(null)
const workspaceState = ref<WorkspaceState | null>(null)
const workspaceSwitching = ref(false)

const sessions = ref<SessionListItem[]>([])
const sessionsCursor = ref<string | null>(null)
const sessionsLoading = ref(false)

const selectedSessionId = ref<string | null>(null)
const selectedTasks = ref<Task[]>([])
const tasksBeforeOrdinal = ref<number | null>(null)

const taskEvents = ref<Record<string, AgentEvent[]>>({})

const incompleteWindows = ref(
  new Set<string>(),
)

const loadingActivity = ref(
  new Set<string>(),
)

const expandedActivity = ref(
  new Set<string>(),
)

const activeTask = ref<Task | null>(null)

const composerPrompt = ref('')

const error = ref('')
const notice = ref('')

const submitting = ref(false)
const checking = ref(false)
const restoring = ref(false)

const connected = ref(false)

const threadEnd = ref<HTMLElement | null>(null)


/* =========================================================
   Computed
   ========================================================= */

const active = computed(() => {
  return (
    activeTask.value?.status === 'PENDING' ||
    activeTask.value?.status === 'RUNNING'
  )
})

const agentReady = computed(() => {
  return metadata.value?.agent_ready === true
})

const loadedActivity = computed(() => {
  return new Set(
    Object.entries(taskEvents.value)
      .filter(([, events]) => events.length > 0)
      .map(([taskId]) => taskId),
  )
})

const thread = computed(() => {
  return buildConversationThread(
    selectedTasks.value.map((task) =>
      buildTaskRun(
        task,
        taskEvents.value[task.id] ?? [],
        !incompleteWindows.value.has(task.id),
      ),
    ),
  )
})


/* =========================================================
   Streams
   ========================================================= */

let closeActiveStream:
  | (() => void)
  | undefined

const historicalStreams =
  new Map<string, () => void>()


/* =========================================================
   URL
   ========================================================= */

function updateUrl(
  sessionId: string | null,
  replace = false,
) {
  const url = new URL(
    window.location.href,
  )

  if (sessionId) {
    url.searchParams.set(
      'session',
      sessionId,
    )
  } else {
    url.searchParams.delete(
      'session',
    )
  }

  const method = replace
    ? 'replaceState'
    : 'pushState'

  window.history[method](
    {},
    '',
    url,
  )
}


/* =========================================================
   Task helpers
   ========================================================= */

function replaceTask(task: Task) {
  const index =
    selectedTasks.value.findIndex(
      (item) => item.id === task.id,
    )

  if (index >= 0) {
    selectedTasks.value[index] = task
  }

  if (
    activeTask.value?.id === task.id
  ) {
    activeTask.value = task
  }
}

function addEvent(
  taskId: string,
  event: AgentEvent,
) {
  const events =
    taskEvents.value[taskId] ?? []

  if (
    !events.some(
      (item) => item.id === event.id,
    )
  ) {
    taskEvents.value = {
      ...taskEvents.value,
      [taskId]: [
        ...events,
        event,
      ],
    }
  }
}


/* =========================================================
   Metadata
   ========================================================= */

async function loadMetadata() {
  try {
    metadata.value =
      await getMetadata()
  } catch {
    metadata.value = null

    error.value =
      '无法连接后端，请启动 coding-agent 并检查代理端口。'
  }
}

async function loadWorkspaces() {
  try {
    workspaceState.value = await getWorkspaces()
  } catch (cause) {
    workspaceState.value = null
    error.value = cause instanceof Error ? cause.message : '加载工作区失败'
  }
}

async function reconnectBackend() {
  await Promise.all([
    loadMetadata(),
    loadWorkspaces(),
    loadSessions(),
  ])
}

function closeAllStreams() {
  closeActiveStream?.()
  closeActiveStream = undefined
  for (const close of historicalStreams.values()) close()
  historicalStreams.clear()
  connected.value = false
}

async function changeWorkspace(path: string) {
  if (active.value || workspaceSwitching.value) return
  workspaceSwitching.value = true
  error.value = ''
  notice.value = ''
  try {
    const switched = await switchWorkspace(path)
    closeAllStreams()
    workspaceState.value = switched
    selectedSessionId.value = null
    selectedTasks.value = []
    tasksBeforeOrdinal.value = null
    taskEvents.value = {}
    incompleteWindows.value = new Set()
    loadingActivity.value = new Set()
    expandedActivity.value = new Set()
    activeTask.value = null
    sessions.value = []
    sessionsCursor.value = null
    saveRecentContext(null)
    updateUrl(null, true)
    await Promise.all([
      loadMetadata(),
      loadSessions(),
    ])
    notice.value = `已切换到工作区：${switched.current.name}`
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 409) {
      error.value = '当前仍有任务正在运行，请等待任务结束后再切换工作区。'
    } else if (cause instanceof ApiError && cause.status === 400) {
      error.value = '工作区必须是本机已存在的绝对目录。'
    } else if (cause instanceof ApiError && cause.status === 503) {
      error.value = '新工作区无法打开，已保留原工作区。'
    } else {
      error.value = cause instanceof Error ? cause.message : '切换工作区失败'
    }
  } finally {
    workspaceSwitching.value = false
  }
}


/* =========================================================
   Sessions
   ========================================================= */

async function loadSessions(
  append = false,
) {
  if (sessionsLoading.value) {
    return
  }

  sessionsLoading.value = true

  try {
    const page =
      await getSessions(
        append
          ? sessionsCursor.value ??
              undefined
          : undefined,
      )

    sessions.value = append
      ? [
          ...sessions.value,
          ...page.items,
        ]
      : page.items

    sessionsCursor.value =
      page.next_cursor
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : '加载历史会话失败'
  } finally {
    sessionsLoading.value = false
  }
}

async function selectSession(
  sessionId: string,
  persist = true,
) {
  restoring.value = true
  error.value = ''

  try {
    const page =
      await getSessionTasks(
        sessionId,
      )

    selectedSessionId.value =
      sessionId

    selectedTasks.value =
      [...page.items].reverse()

    tasksBeforeOrdinal.value =
      page.next_before_ordinal

    if (persist) {
      saveRecentContext(
        sessionId,
        selectedTasks.value.at(-1)?.id,
      )

      updateUrl(sessionId)
    }
  } catch (cause) {
    if (
      cause instanceof ApiError &&
      cause.status === 404
    ) {
      sessions.value =
        sessions.value.filter(
          (item) =>
            item.id !== sessionId,
        )

      selectedSessionId.value =
        null

      selectedTasks.value = []

      saveRecentContext(null)

      updateUrl(null)

      error.value =
        '该历史会话已不存在。'
    } else {
      error.value =
        cause instanceof Error
          ? cause.message
          : '加载会话失败'
    }
  } finally {
    restoring.value = false
  }
}

async function loadEarlierTasks() {
  if (
    !selectedSessionId.value ||
    tasksBeforeOrdinal.value === null
  ) {
    return
  }

  const page =
    await getSessionTasks(
      selectedSessionId.value,
      tasksBeforeOrdinal.value,
    )

  selectedTasks.value = [
    ...page.items,
  ]
    .reverse()
    .concat(
      selectedTasks.value,
    )

  tasksBeforeOrdinal.value =
    page.next_before_ordinal
}


/* =========================================================
   Task refresh
   ========================================================= */

async function refreshTask(
  taskId: string,
) {
  checking.value = true

  try {
    const task =
      await getTask(taskId)

    replaceTask(task)

    await loadSessions()

    if (
      task.status === 'COMPLETED' ||
      task.status === 'FAILED'
    ) {
      if (
        activeTask.value?.id ===
        taskId
      ) {
        activeTask.value = null
      }

      closeActiveStream?.()

      closeActiveStream = undefined

      connected.value = false
    }
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : '查询任务状态失败'
  } finally {
    checking.value = false
  }
}


/* =========================================================
   Active task SSE
   ========================================================= */

function connectActive(
  task: Task,
  fromStart = true,
) {
  /*
   * 当前正在运行的 Task 默认展开执行详情。
   */
  const expanded =
    new Set(
      expandedActivity.value,
    )

  expanded.add(task.id)

  expandedActivity.value =
    expanded

  closeActiveStream?.()

  const after = fromStart
    ? '0'
    : (
        taskEvents.value[
          task.id
        ]?.at(-1)?.id ?? '0'
      )

  closeActiveStream =
    watchTask(
      task.id,
      after,
      {
        onEvent(event) {
          addEvent(
            task.id,
            event,
          )

          if (
            event.type ===
            'task_started'
          ) {
            replaceTask({
              ...task,
              status: 'RUNNING',
            })
          }

          if (
            event.type ===
              'task_completed' ||
            event.type ===
              'task_failed'
          ) {
            void refreshTask(
              task.id,
            )
          }
        },

        onConnection(value) {
          connected.value =
            value
        },

        onHistoryReset() {
          taskEvents.value = {
            ...taskEvents.value,
            [task.id]: [],
          }

          incompleteWindows.value =
            new Set(
              incompleteWindows.value,
            ).add(task.id)

          notice.value =
            '活动窗口已过期，已从当前保留的最早事件重新加载。'
        },

        onTaskMissing() {
          activeTask.value = null

          error.value =
            '活动任务已不存在。'
        },

        onError(message) {
          error.value = message
        },

        onEnd() {
          void refreshTask(
            task.id,
          )
        },
      },
    )
}


/* =========================================================
   Historical activity
   ========================================================= */

function loadActivity(
  task: Task,
) {
  if (
    loadingActivity.value.has(
      task.id,
    ) ||
    taskEvents.value[
      task.id
    ]?.length
  ) {
    return
  }

  loadingActivity.value =
    new Set(
      loadingActivity.value,
    ).add(task.id)

  const finish = () => {
    loadingActivity.value =
      new Set(
        [
          ...loadingActivity.value,
        ].filter(
          (id) =>
            id !== task.id,
        ),
      )

    historicalStreams.delete(
      task.id,
    )
  }

  const close =
    watchTask(
      task.id,
      '0',
      {
        onEvent(event) {
          addEvent(
            task.id,
            event,
          )
        },

        onConnection() {
          // 历史 Event 流不参与 active connection 状态。
        },

        onHistoryReset() {
          incompleteWindows.value =
            new Set(
              incompleteWindows.value,
            ).add(task.id)
        },

        onTaskMissing() {
          finish()
        },

        onError(message) {
          error.value = message
          finish()
        },

        onEnd() {
          finish()
        },
      },
    )

  historicalStreams.set(
    task.id,
    () => {
      close()
      finish()
    },
  )
}


function toggleActivity(
  task: Task,
) {
  const next =
    new Set(
      expandedActivity.value,
    )

  if (
    next.has(task.id)
  ) {
    next.delete(task.id)

    expandedActivity.value =
      next

    return
  }

  next.add(task.id)

  expandedActivity.value =
    next

  if (
    !(
      taskEvents.value[
        task.id
      ]?.length ?? 0
    )
  ) {
    loadActivity(task)
  }
}


/* =========================================================
   Submit
   ========================================================= */

async function submit(
  intent: ComposerIntent,
) {
  if (
    submitting.value ||
    checking.value ||
    active.value ||
    workspaceSwitching.value
  ) {
    return
  }

  submitting.value = true

  error.value = ''

  try {
    const created =
      intent.kind ===
      'follow_up'
        ? await createFollowUp(
            intent.sessionId,
            intent.prompt,
          )
        : await createTask(
            intent.prompt,
          )

    activeTask.value =
      created

    selectedSessionId.value =
      created.session_id

    selectedTasks.value =
      intent.kind ===
      'new_task'
        ? [created]
        : [
            ...selectedTasks.value,
            created,
          ]

    taskEvents.value = {
      ...taskEvents.value,
      [created.id]: [],
    }

    composerPrompt.value = ''

    saveRecentContext(
      created.session_id,
      created.id,
    )

    updateUrl(
      created.session_id,
    )

    await loadSessions()

    connectActive(created)
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : '创建任务失败'
  } finally {
    submitting.value = false
  }
}


/* =========================================================
   New session
   ========================================================= */

async function startNewSession(
  persist = true,
) {
  if (active.value) {
    return
  }

  selectedSessionId.value =
    null

  selectedTasks.value = []

  tasksBeforeOrdinal.value =
    null

  notice.value = ''
  error.value = ''

  if (persist) {
    saveRecentContext(null)

    updateUrl(null)
  }

  await nextTick()

  document
    .querySelector<
      HTMLTextAreaElement
    >('#task-prompt')
    ?.focus()
}



/* =========================================================
   Restore
   ========================================================= */

async function restoreSelection() {
  const query =
    new URL(
      window.location.href,
    ).searchParams.get(
      'session',
    )

  const recent =
    loadRecentContext()

  if (query) {
    await selectSession(
      query,
      false,
    )

    saveRecentContext(
      query,
      selectedTasks.value.at(-1)?.id,
    )

    return
  }

  if (
    recent?.version === 2
  ) {
    await selectSession(
      recent.sessionId,
      false,
    )

    updateUrl(
      recent.sessionId,
      true,
    )

    return
  }

  if (
    recent?.version === 1
  ) {
    try {
      const task =
        await getTask(
          recent.taskId,
        )

      const sessionId =
        task.session_id

      await selectSession(
        sessionId,
        false,
      )

      saveRecentContext(
        sessionId,
        recent.taskId,
      )

      updateUrl(
        sessionId,
        true,
      )

      return
    } catch {
      saveRecentContext(null)
    }
  }
}


/* =========================================================
   Browser history
   ========================================================= */

async function handlePopState() {
  const sessionId =
    new URL(
      window.location.href,
    ).searchParams.get(
      'session',
    )

  if (sessionId) {
    await selectSession(
      sessionId,
      false,
    )
  } else {
    await startNewSession(
      false,
    )
  }
}


/* =========================================================
   Lifecycle
   ========================================================= */

onMounted(async () => {
  window.addEventListener(
    'popstate',
    handlePopState,
  )

  await Promise.all([
    loadMetadata(),
    loadWorkspaces(),
    loadSessions(),
  ])

  await restoreSelection()

  const running =
    selectedTasks.value.find(
      (task) =>
        task.status ===
          'PENDING' ||
        task.status ===
          'RUNNING',
    )

  if (running) {
    activeTask.value =
      running

    connectActive(running)
  }
})

onBeforeUnmount(() => {
  closeAllStreams()

  window.removeEventListener(
    'popstate',
    handlePopState,
  )
})
</script>


<template>
  <div class="app-layout">
    <!-- =====================================================
         Sidebar
         ===================================================== -->

    <Sidebar
      :metadata="metadata"
      :disabled="
        active ||
        sessionsLoading ||
        restoring ||
        submitting ||
        checking ||
        workspaceSwitching
      "
      :history-items="sessions"
      :workspace-state="workspaceState"
      :workspace-switching="workspaceSwitching"

      :selected-id="
        selectedSessionId ??
        undefined
      "

      :loading="
        sessionsLoading
      "

      :has-more="
        sessionsCursor !== null
      "

      @new-task="
        startNewSession
      "

      @reconnect="
        reconnectBackend
      "

      @switch-workspace="
        changeWorkspace
      "

      @select="
        selectSession
      "

      @load-more="
        loadSessions(true)
      "
    />


    <!-- =====================================================
         Workspace
         ===================================================== -->

    <main class="agent-workspace">

      <header class="workspace-topbar">
        <div class="workspace-topbar-content">
          <span>工作区：</span>
          <strong>{{ metadata?.workspace || '等待连接' }}</strong>
          <PhCaretDown :size="15" weight="bold" aria-hidden="true" />
        </div>
      </header>

      <!-- ===================================================
           Missing model configuration
           =================================================== -->

      <div
        v-if="metadata && !agentReady"
        class="notice scaffold"
      >
        <strong>
          模型配置尚不完整。
        </strong>

        <p>
          提交会安全失败，
          不会修改文件。
        </p>
      </div>


      <!-- ===================================================
           Global Feedback
           =================================================== -->

      <p
        v-if="error"
        class="error-banner"
        role="alert"
      >
        {{ error }}
      </p>


      <p
        v-if="notice"
        class="info-banner"
        role="status"
      >
        {{ notice }}
      </p>


      <!-- ===================================================
           Session History Actions

           这里只保留“加载更早任务”。

           没有更早任务时整个 div 都不会存在，
           因此不会留下空白高度。
           =================================================== -->

      <div
        v-if="
          selectedSessionId &&
          tasksBeforeOrdinal !== null
        "
        class="history-actions"
      >
        <button
          class="secondary compact-button"
          type="button"
          @click="
            loadEarlierTasks
          "
        >
          加载更早任务
        </button>
      </div>


      <!-- ===================================================
           Conversation
           =================================================== -->

      <ConversationThread
        :thread="
          thread
        "

        :loading-activity="
          loadingActivity
        "

        :loaded-activity="
          loadedActivity
        "

        :expanded-activity="
          expandedActivity
        "

        @toggle-activity="
          toggleActivity
        "
      />


      <div
        ref="threadEnd"
        class="thread-end"
        aria-hidden="true"
      />


      <!-- ===================================================
           Connection Recovery
           =================================================== -->

      <div
        v-if="
          active &&
          !connected
        "

        class="connection-banner"

        role="status"
      >
        活动任务的事件流暂未连接；
        任务不会被重复创建。

        <button
          class="secondary"

          :disabled="
            checking
          "

          @click="
            refreshTask(
              activeTask!.id,
            )
          "
        >
          查询状态
        </button>


        <button
          class="secondary"

          @click="
            connectActive(
              activeTask!,
              false,
            )
          "
        >
          立即重连
        </button>
      </div>


      <!-- ===================================================
           Composer
           =================================================== -->

      <TaskComposer
        v-model="
          composerPrompt
        "

        :session-id="
          selectedSessionId ??
          undefined
        "

        :disabled="
          submitting ||
          checking ||
          restoring ||
          workspaceSwitching ||
          active ||
          !metadata
        "

        :busy="
          active
        "

        @submit="
          submit
        "
      />

    </main>
  </div>
</template>
