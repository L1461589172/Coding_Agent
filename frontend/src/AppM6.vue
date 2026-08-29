<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError, createFollowUp, createTask, deleteSession, getMetadata, getSessionTasks,
  getSessions, getTask, watchTask,
} from './api/client'
import ConversationThread from './components/ConversationThread.vue'
import Sidebar from './components/Sidebar.vue'
import TaskComposer from './components/TaskComposer.vue'
import { loadRecentContext, saveRecentContext } from './state/recentContext'
import { buildConversationThread } from './thread/buildConversationThread'
import { buildTaskRun } from './thread/buildTaskRun'
import type { ComposerIntent } from './thread/types'
import type { AgentEvent, Metadata, SessionListItem, Task } from './types'

const metadata = ref<Metadata | null>(null)
const sessions = ref<SessionListItem[]>([])
const sessionsCursor = ref<string | null>(null)
const sessionsLoading = ref(false)
const selectedSessionId = ref<string | null>(null)
const selectedTasks = ref<Task[]>([])
const tasksBeforeOrdinal = ref<number | null>(null)
const taskEvents = ref<Record<string, AgentEvent[]>>({})
const incompleteWindows = ref(new Set<string>())
const loadingActivity = ref(new Set<string>())
const activeTask = ref<Task | null>(null)
const composerPrompt = ref('')
const error = ref('')
const notice = ref('')
const submitting = ref(false)
const checking = ref(false)
const restoring = ref(false)
const connected = ref(false)
const threadEnd = ref<HTMLElement | null>(null)

const active = computed(() => activeTask.value?.status === 'PENDING' || activeTask.value?.status === 'RUNNING')
const agentReady = computed(() => metadata.value?.agent_ready === true)
const thread = computed(() => buildConversationThread(selectedTasks.value.map((task) => buildTaskRun(
  task, taskEvents.value[task.id] ?? [], !incompleteWindows.value.has(task.id),
))))

let closeActiveStream: (() => void) | undefined
const historicalStreams = new Map<string, () => void>()

function updateUrl(sessionId: string | null, replace = false) {
  const url = new URL(window.location.href)
  if (sessionId) url.searchParams.set('session', sessionId)
  else url.searchParams.delete('session')
  const method = replace ? 'replaceState' : 'pushState'
  window.history[method]({}, '', url)
}

function replaceTask(task: Task) {
  const index = selectedTasks.value.findIndex((item) => item.id === task.id)
  if (index >= 0) selectedTasks.value[index] = task
  if (activeTask.value?.id === task.id) activeTask.value = task
}

function addEvent(taskId: string, event: AgentEvent) {
  const events = taskEvents.value[taskId] ?? []
  if (!events.some((item) => item.id === event.id)) {
    taskEvents.value = { ...taskEvents.value, [taskId]: [...events, event] }
  }
}

async function loadMetadata() {
  try { metadata.value = await getMetadata() }
  catch { metadata.value = null; error.value = '无法连接后端，请启动 coding-agent 并检查代理端口。' }
}

async function loadSessions(append = false) {
  if (sessionsLoading.value) return
  sessionsLoading.value = true
  try {
    const page = await getSessions(append ? sessionsCursor.value ?? undefined : undefined)
    sessions.value = append ? [...sessions.value, ...page.items] : page.items
    sessionsCursor.value = page.next_cursor
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载历史会话失败'
  } finally { sessionsLoading.value = false }
}

async function selectSession(sessionId: string, persist = true) {
  restoring.value = true
  error.value = ''
  try {
    const page = await getSessionTasks(sessionId)
    selectedSessionId.value = sessionId
    selectedTasks.value = [...page.items].reverse()
    tasksBeforeOrdinal.value = page.next_before_ordinal
    if (persist) {
      saveRecentContext(sessionId, selectedTasks.value.at(-1)?.id)
      updateUrl(sessionId)
    }
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      sessions.value = sessions.value.filter((item) => item.id !== sessionId)
      selectedSessionId.value = null
      selectedTasks.value = []
      saveRecentContext(null)
      updateUrl(null)
      error.value = '该历史会话已不存在。'
    } else error.value = cause instanceof Error ? cause.message : '加载会话失败'
  } finally { restoring.value = false }
}

async function loadEarlierTasks() {
  if (!selectedSessionId.value || tasksBeforeOrdinal.value === null) return
  const page = await getSessionTasks(selectedSessionId.value, tasksBeforeOrdinal.value)
  selectedTasks.value = [...page.items].reverse().concat(selectedTasks.value)
  tasksBeforeOrdinal.value = page.next_before_ordinal
}

async function refreshTask(taskId: string) {
  checking.value = true
  try {
    const task = await getTask(taskId)
    replaceTask(task)
    await loadSessions()
    if (task.status === 'COMPLETED' || task.status === 'FAILED') {
      if (activeTask.value?.id === taskId) activeTask.value = null
      closeActiveStream?.()
      closeActiveStream = undefined
      connected.value = false
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '查询任务状态失败'
  } finally { checking.value = false }
}

function connectActive(task: Task, fromStart = true) {
  closeActiveStream?.()
  const after = fromStart ? '0' : (taskEvents.value[task.id]?.at(-1)?.id ?? '0')
  closeActiveStream = watchTask(task.id, after, {
    onEvent(event) {
      addEvent(task.id, event)
      if (event.type === 'task_started') replaceTask({ ...task, status: 'RUNNING' })
      if (event.type === 'task_completed' || event.type === 'task_failed') void refreshTask(task.id)
    },
    onConnection(value) { connected.value = value },
    onHistoryReset() {
      taskEvents.value = { ...taskEvents.value, [task.id]: [] }
      incompleteWindows.value = new Set(incompleteWindows.value).add(task.id)
      notice.value = '活动窗口已过期，已从当前保留的最早事件重新加载。'
    },
    onTaskMissing() { activeTask.value = null; error.value = '活动任务已不存在。' },
    onError(message) { error.value = message },
    onEnd() { void refreshTask(task.id) },
  })
}

function loadActivity(task: Task) {
  if (loadingActivity.value.has(task.id) || taskEvents.value[task.id]?.length) return
  loadingActivity.value = new Set(loadingActivity.value).add(task.id)
  const finish = () => {
    loadingActivity.value = new Set([...loadingActivity.value].filter((id) => id !== task.id))
    historicalStreams.delete(task.id)
  }
  const close = watchTask(task.id, '0', {
    onEvent: (event) => addEvent(task.id, event),
    onConnection: () => {},
    onHistoryReset: () => { incompleteWindows.value = new Set(incompleteWindows.value).add(task.id) },
    onTaskMissing: finish,
    onError(message) { error.value = message; finish() },
    onEnd: finish,
  })
  historicalStreams.set(task.id, () => { close(); finish() })
}

async function submit(intent: ComposerIntent) {
  if (submitting.value || checking.value || active.value) return
  submitting.value = true
  error.value = ''
  try {
    const created = intent.kind === 'follow_up'
      ? await createFollowUp(intent.sessionId, intent.prompt)
      : await createTask(intent.prompt)
    activeTask.value = created
    selectedSessionId.value = created.session_id
    selectedTasks.value = intent.kind === 'new_task' ? [created] : [...selectedTasks.value, created]
    taskEvents.value = { ...taskEvents.value, [created.id]: [] }
    composerPrompt.value = ''
    saveRecentContext(created.session_id, created.id)
    updateUrl(created.session_id)
    await loadSessions()
    connectActive(created)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '创建任务失败'
  } finally { submitting.value = false }
}

async function startNewSession(persist = true) {
  if (active.value) return
  selectedSessionId.value = null
  selectedTasks.value = []
  tasksBeforeOrdinal.value = null
  notice.value = ''
  error.value = ''
  if (persist) {
    saveRecentContext(null)
    updateUrl(null)
  }
  await nextTick()
  document.querySelector<HTMLTextAreaElement>('#task-prompt')?.focus()
}

async function removeSelectedSession() {
  const sessionId = selectedSessionId.value
  if (!sessionId || activeTask.value?.session_id === sessionId) return
  if (!window.confirm('确定删除该会话及其全部本地历史吗？此操作不可撤销。')) return
  try {
    await deleteSession(sessionId)
    sessions.value = sessions.value.filter((item) => item.id !== sessionId)
    await startNewSession()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '删除会话失败' }
}

async function restoreSelection() {
  const query = new URL(window.location.href).searchParams.get('session')
  const recent = loadRecentContext()
  if (query) {
    await selectSession(query, false)
    saveRecentContext(query, selectedTasks.value.at(-1)?.id)
    return
  }
  if (recent?.version === 2) {
    await selectSession(recent.sessionId, false)
    updateUrl(recent.sessionId, true)
    return
  }
  if (recent?.version === 1) {
    try {
      const sessionId = (await getTask(recent.taskId)).session_id
      await selectSession(sessionId, false)
      saveRecentContext(sessionId, recent.taskId)
      updateUrl(sessionId, true)
      return
    }
    catch { saveRecentContext(null) }
  }
}

async function handlePopState() {
  const sessionId = new URL(window.location.href).searchParams.get('session')
  if (sessionId) await selectSession(sessionId, false)
  else await startNewSession(false)
}

onMounted(async () => {
  window.addEventListener('popstate', handlePopState)
  await Promise.all([loadMetadata(), loadSessions()])
  await restoreSelection()
  const running = selectedTasks.value.find((task) => task.status === 'PENDING' || task.status === 'RUNNING')
  if (running) { activeTask.value = running; connectActive(running) }
})

onBeforeUnmount(() => {
  closeActiveStream?.()
  for (const close of historicalStreams.values()) close()
  window.removeEventListener('popstate', handlePopState)
})
</script>

<template>
  <div class="app-layout">
    <Sidebar :metadata="metadata" :disabled="active" :history-items="sessions"
      :selected-id="selectedSessionId ?? undefined" :loading="sessionsLoading"
      :has-more="sessionsCursor !== null" @new-task="startNewSession" @reconnect="loadMetadata"
      @select="selectSession" @load-more="loadSessions(true)" />
    <main class="agent-workspace">
      <header class="workspace-header">
        <div><span class="eyebrow">{{ metadata?.workspace || 'Coding Workspace' }}</span><h1>会话工作台</h1></div>
        <div class="runtime-state" :class="{ ready: agentReady }" role="status"><span>●</span>
          {{ active ? 'Agent 正在执行' : agentReady ? 'Agent 已就绪' : '安全诊断模式' }}
        </div>
      </header>
      <div class="notice" :class="{ scaffold: metadata && !agentReady }">
        <strong>{{ agentReady ? '历史与执行事实均来自本地 Workspace。' : '模型配置尚不完整。' }}</strong>
        <p>{{ agentReady ? '多轮上下文使用有界任务回顾；文件系统始终是当前代码事实来源。' : '提交会安全失败，不会修改文件。' }}</p>
      </div>
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <p v-if="notice" class="info-banner" role="status">{{ notice }}</p>
      <div v-if="selectedSessionId" class="history-actions">
        <button v-if="tasksBeforeOrdinal !== null" class="secondary" @click="loadEarlierTasks">加载更早任务</button>
        <button v-for="task in selectedTasks" :key="task.id" class="secondary"
          :disabled="loadingActivity.has(task.id) || (taskEvents[task.id]?.length ?? 0) > 0"
          @click="loadActivity(task)">
          {{ loadingActivity.has(task.id) ? `加载 #${task.ordinal}…` : `查看 #${task.ordinal} 活动` }}
        </button>
        <button class="danger" :disabled="activeTask?.session_id === selectedSessionId" @click="removeSelectedSession">删除会话</button>
      </div>
      <ConversationThread :thread="thread" />
      <div ref="threadEnd" class="thread-end" aria-hidden="true" />
      <div v-if="active && !connected" class="connection-banner" role="status">
        活动任务的事件流暂未连接；任务不会被重复创建。
        <button class="secondary" :disabled="checking" @click="refreshTask(activeTask!.id)">查询状态</button>
        <button class="secondary" @click="connectActive(activeTask!, false)">立即重连</button>
      </div>
      <TaskComposer v-model="composerPrompt" :session-id="selectedSessionId ?? undefined"
        :disabled="submitting || checking || restoring || active || !metadata" :busy="active" @submit="submit" />
      <footer>确定性 Activity · Runtime Summary · 持久多轮 TaskRun</footer>
    </main>
  </div>
</template>
