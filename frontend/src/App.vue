<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, createTask, getMetadata, getTask, watchTask } from './api/client'
import ConversationThread from './components/ConversationThread.vue'
import Sidebar from './components/Sidebar.vue'
import TaskComposer from './components/TaskComposer.vue'
import { loadRecentContext, saveRecentTask } from './state/recentContext'
import { buildConversationThread } from './thread/buildConversationThread'
import { buildTaskRun } from './thread/buildTaskRun'
import type { ComposerIntent } from './thread/types'
import type { AgentEvent, Metadata, Task } from './types'

const metadata = ref<Metadata | null>(null)
const selectedTask = ref<Task | null>(null)
const selectedEvents = ref<AgentEvent[]>([])
const activeTask = ref<Task | null>(null)
const eventWindowComplete = ref(true)
const composerPrompt = ref('')
const error = ref('')
const submitting = ref(false)
const connected = ref(false)
const checking = ref(false)
const restoring = ref(false)
const connectionNotice = ref('')
const threadEnd = ref<HTMLElement | null>(null)
const active = computed(() => (
  activeTask.value?.status === 'PENDING' || activeTask.value?.status === 'RUNNING'
))
const agentReady = computed(() => metadata.value?.agent_ready === true)
const thread = computed(() => buildConversationThread(
  selectedTask.value
    ? [buildTaskRun(selectedTask.value, selectedEvents.value, eventWindowComplete.value)]
    : [],
))
let closeStream: (() => void) | undefined
let followLatest = true

function updateFollowLatest() {
  const remaining = document.documentElement.scrollHeight - window.innerHeight - window.scrollY
  followLatest = remaining < 180
}

watch(
  [() => selectedEvents.value.length, () => selectedTask.value?.summary],
  async () => {
    if (!followLatest) return
    await nextTick()
    threadEnd.value?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'end',
    })
  },
)

async function loadMetadata() {
  try {
    metadata.value = await getMetadata()
    error.value = ''
  } catch {
    metadata.value = null
    error.value = '无法连接后端，请先启动 coding-agent，并检查代理端口。'
  }
}

function updateTask(taskId: string, mutate: (task: Task) => void) {
  if (activeTask.value?.id === taskId) mutate(activeTask.value)
  if (selectedTask.value?.id === taskId) mutate(selectedTask.value)
}

function handleTaskMissing(taskId: string) {
  closeStream?.()
  closeStream = undefined
  connected.value = false
  if (activeTask.value?.id === taskId) activeTask.value = null
  if (selectedTask.value?.id === taskId) {
    selectedTask.value = null
    selectedEvents.value = []
  }
  saveRecentTask(null)
  error.value = '后端已重启或任务历史已清空，之前的内存任务无法恢复；请重新提交任务。'
}

function connect(taskId: string, fromStart = false) {
  closeStream?.()
  closeStream = undefined
  const after = fromStart || selectedTask.value?.id !== taskId
    ? '0'
    : (selectedEvents.value.at(-1)?.id ?? '0')
  closeStream = watchTask(taskId, after, {
    onEvent(event) {
      if (selectedTask.value?.id === taskId
        && !selectedEvents.value.some((item) => item.id === event.id)) {
        selectedEvents.value.push(event)
      }
      if (event.type === 'task_started') {
        updateTask(taskId, (task) => { task.status = 'RUNNING' })
      }
      if (event.type === 'task_completed' || event.type === 'task_failed') {
        const expected = event.type === 'task_completed' ? 'COMPLETED' : 'FAILED'
        updateTask(taskId, (task) => { task.status = expected })
        closeStream?.()
        closeStream = undefined
        connected.value = false
        void refreshTask(taskId, expected)
      }
    },
    onConnection(value) { connected.value = value },
    onHistoryReset() {
      if (selectedTask.value?.id === taskId) {
        selectedEvents.value = []
        eventWindowComplete.value = false
      }
      connectionNotice.value = '事件历史窗口已过期；已从服务器当前保留的最早事件重新加载。'
    },
    onTaskMissing: () => handleTaskMissing(taskId),
    onError(message) {
      connected.value = false
      error.value = message
    },
    onEnd() {
      connected.value = false
      void refreshTask(taskId)
    },
  })
}

async function refreshTask(taskId: string, expected?: 'COMPLETED' | 'FAILED') {
  checking.value = true
  try {
    const latest = await getTask(taskId)
    if (selectedTask.value?.id === taskId) selectedTask.value = latest
    if (activeTask.value?.id === taskId) activeTask.value = latest
    if (expected && latest.status !== expected) {
      error.value = `终态不一致：事件为 ${expected}，任务接口为 ${latest.status}。请保留现场检查后端。`
    } else {
      error.value = ''
    }
    if (latest.status === 'COMPLETED' || latest.status === 'FAILED') {
      closeStream?.()
      closeStream = undefined
      connected.value = false
      if (activeTask.value?.id === taskId) activeTask.value = null
    }
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) handleTaskMissing(taskId)
    else error.value = '任务状态查询失败；不会自动重复提交，请稍后重新查询。'
  } finally {
    checking.value = false
  }
}

async function restoreTask() {
  const recent = loadRecentContext()
  if (!recent) return
  restoring.value = true
  try {
    const restored = await getTask(recent.taskId)
    selectedTask.value = restored
    selectedEvents.value = []
    eventWindowComplete.value = true
    if (restored.status === 'PENDING' || restored.status === 'RUNNING') {
      activeTask.value = { ...restored }
    }
    connectionNotice.value = '已恢复刷新前的任务，并回放服务器仍保留的活动。'
    connect(restored.id, true)
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) handleTaskMissing(recent.taskId)
    else error.value = '无法恢复上次任务；后端暂时不可用，请重新连接后再查询。'
  } finally {
    restoring.value = false
  }
}

async function submit(intent: ComposerIntent) {
  if (intent.kind !== 'new_task' || submitting.value || checking.value || active.value) return
  submitting.value = true
  error.value = ''
  closeStream?.()
  try {
    const created = await createTask(intent.prompt)
    activeTask.value = { ...created }
    selectedTask.value = { ...created }
    selectedEvents.value = []
    eventWindowComplete.value = true
    connectionNotice.value = ''
    composerPrompt.value = ''
    saveRecentTask(created.id)
    connect(created.id, true)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '创建任务失败'
  } finally {
    submitting.value = false
  }
}

async function startNewTask() {
  if (active.value) return
  closeStream?.()
  closeStream = undefined
  selectedTask.value = null
  selectedEvents.value = []
  eventWindowComplete.value = true
  connectionNotice.value = ''
  error.value = ''
  saveRecentTask(null)
  await nextTick()
  document.querySelector<HTMLTextAreaElement>('#task-prompt')?.focus()
}

onMounted(async () => {
  window.addEventListener('scroll', updateFollowLatest, { passive: true })
  await loadMetadata()
  await restoreTask()
})
onBeforeUnmount(() => {
  closeStream?.()
  window.removeEventListener('scroll', updateFollowLatest)
})
</script>

<template>
  <div class="app-layout">
    <Sidebar :metadata="metadata" :disabled="active" @new-task="startNewTask" @reconnect="loadMetadata" />
    <main class="agent-workspace">
      <header class="workspace-header">
        <div>
          <span class="eyebrow">{{ metadata?.workspace || 'Coding Workspace' }}</span>
          <h1>任务工作台</h1>
        </div>
        <div class="runtime-state" :class="{ ready: agentReady }" role="status">
          <span aria-hidden="true">{{ active ? '◌' : agentReady ? '●' : '○' }}</span>
          {{ active ? 'Agent 正在执行' : agentReady ? 'Agent 已就绪' : '安全诊断模式' }}
        </div>
      </header>

      <div class="notice" :class="{ scaffold: metadata && !agentReady }">
        <strong>{{ agentReady ? '工具执行来自本地 Workspace。' : '模型配置尚不完整。' }}</strong>
        <p v-if="agentReady">活动文案来自结构化 Runtime 事实；请核对 Diff、命令退出状态和最终 Summary。</p>
        <p v-else>当前提交会安全地以 NOT_IMPLEMENTED 结束，不会操作文件或运行命令。</p>
      </div>
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <p v-if="connectionNotice" class="info-banner" role="status">{{ connectionNotice }}</p>

      <ConversationThread :thread="thread" />
      <div ref="threadEnd" class="thread-end" aria-hidden="true" />

      <div v-if="active && selectedTask?.id === activeTask?.id && !connected" class="connection-banner" role="status">
        事件流暂未连接；浏览器会有界重连，任务不会被重复创建。
        <div>
          <button class="secondary" :disabled="checking" @click="refreshTask(activeTask!.id)">查询状态</button>
          <button class="secondary" @click="connect(activeTask!.id, false)">立即重连</button>
        </div>
      </div>

      <TaskComposer v-model="composerPrompt"
        :disabled="submitting || checking || restoring || active || !metadata"
        :busy="active" @submit="submit" />
      <footer>确定性 Activity · Runtime Summary · M6-ready TaskRun</footer>
    </main>
  </div>
</template>
