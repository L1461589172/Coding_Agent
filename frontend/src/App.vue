<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { createTask, getMetadata, getTask, watchTask } from './api/client'
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
const active = computed(() => task.value?.status === 'PENDING' || task.value?.status === 'RUNNING')
let closeStream: (() => void) | undefined

async function loadMetadata() {
  try { metadata.value = await getMetadata(); error.value = '' }
  catch { metadata.value = null; error.value = '无法连接后端，请先启动 coding-agent，并检查代理端口。' }
}

function connect() {
  closeStream?.()
  if (!task.value) return
  closeStream = watchTask(task.value.id, events.value.at(-1)?.id ?? '0', (event) => {
    if (!events.value.some((item) => item.id === event.id)) events.value.push(event)
    if (task.value && event.type === 'task_started') task.value.status = 'RUNNING'
    if (task.value && (event.type === 'task_completed' || event.type === 'task_failed')) {
      task.value.status = event.type === 'task_completed' ? 'COMPLETED' : 'FAILED'
      closeStream?.()
      connected.value = false
      void refreshTask()
    }
  }, (value) => { connected.value = value })
}

async function refreshTask() {
  if (!task.value) return
  checking.value = true
  try { task.value = await getTask(task.value.id); error.value = '' }
  catch { error.value = '任务状态查询失败；不要重复提交，请稍后重新查询。' }
  finally { checking.value = false }
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
    connect()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '创建任务失败'
  } finally { submitting.value = false }
}

onMounted(loadMetadata)
onBeforeUnmount(() => closeStream?.())
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand"><span class="brand-icon" aria-hidden="true">&gt;_</span><div><h1>Coding Agent</h1><p>LOCAL DEVELOPMENT WORKSPACE</p></div></div>
      <span class="badge">M1 · 本地工具</span>
    </header>
    <main>
      <aside class="workspace-panel">
        <h2>工作区</h2>
        <p class="workspace-name">{{ metadata?.workspace || '尚未连接' }}</p>
        <p class="muted">单用户 / 单工作区 / 单活动任务</p>
        <hr />
        <h2>工具协议</h2>
        <ul class="tool-list"><li v-for="tool in metadata?.tools ?? []" :key="tool"><code>{{ tool }}</code><span>{{ metadata?.tool_statuses?.[tool] === 'ready' ? '工具就绪' : '待实现' }}</span></li></ul>
        <p class="muted">六个本地工具已实现，尚未接入 Agent。页面任务仍只检查链路，不读取、修改文件或执行命令。</p>
        <button class="secondary" @click="loadMetadata">重新连接后端</button>
      </aside>
      <section class="main-panel" aria-label="任务工作台">
        <div class="notice"><strong>基础链路已准备，Agent 能力待接入。</strong><p>提交后会产生任务与事件，并以 NOT_IMPLEMENTED 结束。这不代表真实编程任务已完成。</p></div>
        <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
        <TaskInput :disabled="submitting || checking || active || !metadata" @submit="submit" />
        <TaskStatus :task="task" />
        <div v-if="task && active && !connected" class="connection-banner" role="status">
          事件流未连接；浏览器会自动重连。可查询状态或手动重连，不会重新创建任务。
          <button class="secondary" :disabled="checking" @click="refreshTask">查询状态</button>
          <button class="secondary" @click="connect">重连事件流</button>
        </div>
        <section class="timeline-section"><h2>Agent Timeline <span class="muted">{{ events.length }} 个事件</span></h2><AgentTimeline :events="events" /></section>
        <section v-if="task?.error || task?.result" class="result-panel" aria-live="polite">
          <h2>最终结果</h2>
          <p v-if="task.error"><code>{{ task.error.code }}</code> — {{ task.error.message }}</p>
          <pre v-else>{{ task.result }}</pre>
        </section>
      </section>
    </main>
    <footer>自研 Runtime 框架 · 当前未调用模型、未修改文件、未执行测试命令</footer>
  </div>
</template>
