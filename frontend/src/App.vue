<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, createTask, getMetadata, getTask, watchTask } from './api/client'
import AgentTimeline from './components/AgentTimeline.vue'
import TaskInput from './components/TaskInput.vue'
import TaskStatus from './components/TaskStatus.vue'
import type { AgentEvent, Metadata, Task } from './types'

const metadata = ref<Metadata | null>(null)
const task = ref<Task | null>(null)
const events = ref<AgentEvent[]>([])
const error = ref('')
const submitting = ref(false)
const connected = ref(false)
const checking = ref(false)
const restoring = ref(false)
const connectionNotice = ref('')
const active = computed(() => task.value?.status === 'PENDING' || task.value?.status === 'RUNNING')
const agentReady = computed(() => metadata.value?.agent_ready === true)
let closeStream: (() => void) | undefined
const TASK_STORAGE_KEY = 'coding-agent:last-task-id'

function rememberTask(id: string | null) {
  try {
    if (id) localStorage.setItem(TASK_STORAGE_KEY, id)
    else localStorage.removeItem(TASK_STORAGE_KEY)
  } catch { /* The app still works when browser storage is disabled. */ }
}

function rememberedTask(): string | null {
  try { return localStorage.getItem(TASK_STORAGE_KEY) }
  catch { return null }
}

async function loadMetadata() {
  try { metadata.value = await getMetadata(); error.value = '' }
  catch { metadata.value = null; error.value = '无法连接后端，请先启动 coding-agent，并检查代理端口。' }
}

function handleTaskMissing() {
  closeStream?.()
  closeStream = undefined
  connected.value = false
  task.value = null
  events.value = []
  rememberTask(null)
  error.value = '后端已重启或任务历史已清空，之前的内存任务无法恢复；请重新提交任务。'
}

function connect(fromStart = false) {
  closeStream?.()
  closeStream = undefined
  if (!task.value) return
  const taskId = task.value.id
  const after = fromStart ? '0' : (events.value.at(-1)?.id ?? '0')
  closeStream = watchTask(taskId, after, {
    onEvent(event) {
      if (task.value?.id !== taskId) return
      if (!events.value.some((item) => item.id === event.id)) events.value.push(event)
      if (event.type === 'task_started') task.value.status = 'RUNNING'
      if (event.type === 'task_completed' || event.type === 'task_failed') {
        const expected = event.type === 'task_completed' ? 'COMPLETED' : 'FAILED'
        task.value.status = expected
        closeStream?.()
        closeStream = undefined
        connected.value = false
        void refreshTask(expected)
      }
    },
    onConnection(value) { connected.value = value },
    onHistoryReset() {
      events.value = []
      connectionNotice.value = '事件历史窗口已过期；时间线已从服务器当前保留的最早事件重新加载。'
    },
    onTaskMissing: handleTaskMissing,
    onError(message) {
      connected.value = false
      error.value = message
    },
    onEnd() {
      connected.value = false
      void refreshTask()
    },
  })
}

async function refreshTask(expected?: 'COMPLETED' | 'FAILED') {
  if (!task.value) return
  const taskId = task.value.id
  checking.value = true
  try {
    const latest = await getTask(taskId)
    if (task.value?.id !== taskId) return
    task.value = latest
    if (expected && latest.status !== expected) {
      error.value = `终态不一致：事件为 ${expected}，任务接口为 ${latest.status}。请保留现场检查后端。`
    } else {
      error.value = ''
    }
    if (latest.status === 'COMPLETED' || latest.status === 'FAILED') {
      closeStream?.()
      closeStream = undefined
      connected.value = false
    }
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) handleTaskMissing()
    else error.value = '任务状态查询失败；不会自动重复提交，请稍后重新查询。'
  }
  finally { checking.value = false }
}

async function restoreTask() {
  const id = rememberedTask()
  if (!id) return
  restoring.value = true
  try {
    task.value = await getTask(id)
    events.value = []
    connectionNotice.value = '已恢复浏览器刷新前的任务，并从服务器回放仍保留的事件。'
    connect(true)
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) handleTaskMissing()
    else error.value = '无法恢复上次任务；后端暂时不可用，请重新连接后再查询。'
  } finally {
    restoring.value = false
  }
}

async function submit(prompt: string) {
  if (submitting.value || checking.value || active.value) return
  submitting.value = true
  error.value = ''
  closeStream?.()
  try {
    const created = await createTask(prompt)
    task.value = created
    events.value = []
    connectionNotice.value = ''
    rememberTask(created.id)
    connect(true)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '创建任务失败'
  } finally { submitting.value = false }
}

onMounted(async () => {
  await loadMetadata()
  await restoreTask()
})
onBeforeUnmount(() => closeStream?.())
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand"><span class="brand-icon" aria-hidden="true">&gt;_</span><div><h1>Coding Agent</h1><p>LOCAL DEVELOPMENT WORKSPACE</p></div></div>
      <span class="badge">M3 · Agent Runtime</span>
    </header>
    <main>
      <aside class="workspace-panel">
        <h2>工作区</h2>
        <p class="workspace-name">{{ metadata?.workspace || '尚未连接' }}</p>
        <p class="muted">单用户 / 单工作区 / 单活动任务</p>
        <hr />
        <h2>工具协议</h2>
        <ul class="tool-list"><li v-for="tool in metadata?.tools ?? []" :key="tool"><code>{{ tool }}</code><span>{{ metadata?.tool_statuses?.[tool] === 'ready' ? '工具就绪' : '待实现' }}</span></li></ul>
        <p class="muted">六个本地工具已接入 Agent Loop；运行过程会展示参数、结果、Diff 与命令输出。</p>
        <button class="secondary" @click="loadMetadata">重新连接后端</button>
      </aside>
      <section class="main-panel" aria-label="任务工作台">
        <div class="notice" :class="{ scaffold: metadata && !agentReady }">
          <strong>{{ agentReady ? 'Agent 已就绪。' : 'Agent Loop 已就绪，模型配置尚不完整。' }}</strong>
          <p v-if="agentReady">提交后模型可以调用本地工具；请在专用 Workspace 中运行，并核对每项真实结果。</p>
          <p v-else>配置 API Key、Base URL 和模型名后重启后端；当前任务会安全地以 NOT_IMPLEMENTED 结束。</p>
        </div>
        <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
        <p v-if="connectionNotice" class="info-banner" role="status">{{ connectionNotice }}</p>
        <TaskInput :disabled="submitting || checking || restoring || active || !metadata" @submit="submit" />
        <TaskStatus :task="task" />
        <div v-if="task && active && !connected" class="connection-banner" role="status">
          事件流未连接；浏览器会按有界退避自动重连。可查询状态或立即重连，不会重新创建任务。
          <button class="secondary" :disabled="checking" @click="refreshTask()">查询状态</button>
          <button class="secondary" @click="connect(false)">重连事件流</button>
        </div>
        <section class="timeline-section"><h2>Agent Timeline <span class="muted">{{ events.length }} 个事件</span></h2><AgentTimeline :events="events" /></section>
        <section v-if="task?.error || task?.result" class="result-panel" aria-live="polite">
          <h2>最终结果</h2>
          <p v-if="task.error"><code>{{ task.error.code }}</code> — {{ task.error.message }}</p>
          <pre v-else>{{ task.result }}</pre>
        </section>
      </section>
    </main>
    <footer>自研 Agent Runtime · 工具结果来自本地 Workspace，页面不会执行模型或 Shell</footer>
  </div>
</template>
