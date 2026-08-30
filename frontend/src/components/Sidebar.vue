<script setup lang="ts">
import { ref, watch } from 'vue'

import type { Metadata, SessionListItem, WorkspaceState } from '../types'

const props = withDefaults(defineProps<{
  metadata: Metadata | null
  workspaceState?: WorkspaceState | null
  workspaceSwitching?: boolean
  disabled?: boolean
  historyItems?: SessionListItem[]
  selectedId?: string
  loading?: boolean
  hasMore?: boolean
}>(), {
  disabled: false,
  workspaceState: null,
  workspaceSwitching: false,
  historyItems: () => [],
  selectedId: undefined,
  loading: false,
  hasMore: false,
})

const emit = defineEmits<{
  newTask: []
  reconnect: []
  switchWorkspace: [path: string]
  select: [id: string]
  loadMore: []
}>()

const workspacePath = ref('')
const switcherOpen = ref(false)

watch(
  () => props.metadata?.workspace_path,
  (path) => {
    workspacePath.value = path ?? ''
    if (path) switcherOpen.value = false
  },
  { immediate: true },
)

function submitWorkspace() {
  const path = workspacePath.value.trim()
  if (path) emit('switchWorkspace', path)
}
</script>

<template>
  <aside class="sidebar" aria-label="工作区导航">
    <div class="sidebar-brand">
      <span class="brand-icon" aria-hidden="true">&gt;_</span>
      <div><strong>Coding Agent</strong><span>LOCAL AGENT</span></div>
    </div>
    <section class="workspace-card" aria-labelledby="workspace-title">
      <span id="workspace-title" class="eyebrow">工作区</span>
      <p class="workspace-name">{{ metadata?.workspace || '尚未连接' }}</p>
      <p v-if="metadata?.workspace_path" class="workspace-path" :title="metadata.workspace_path">
        {{ metadata.workspace_path }}
      </p>
      <p class="readiness" :class="{ ready: metadata?.agent_ready }">
        <span aria-hidden="true">{{ metadata?.agent_ready ? '●' : '○' }}</span>
        {{ metadata?.agent_ready ? 'Agent Ready' : '模型未配置' }}
      </p>
      <button class="workspace-toggle" type="button"
        :disabled="disabled || workspaceSwitching || !metadata"
        :aria-expanded="switcherOpen" @click="switcherOpen = !switcherOpen">
        {{ switcherOpen ? '取消切换' : '切换工作区' }}
      </button>
      <form v-if="switcherOpen" class="workspace-switcher" @submit.prevent="submitWorkspace">
        <template v-if="(workspaceState?.recent.length ?? 0) > 1">
          <label for="recent-workspace">最近使用</label>
          <select id="recent-workspace" v-model="workspacePath" :disabled="workspaceSwitching">
            <option v-for="item in workspaceState?.recent ?? []" :key="item.path"
              :value="item.path">{{ item.name }} — {{ item.path }}</option>
          </select>
        </template>
        <label for="workspace-path">绝对路径</label>
        <input id="workspace-path" v-model="workspacePath" type="text"
          list="recent-workspaces" autocomplete="off" spellcheck="false"
          placeholder="D:\Projects\my-project" :disabled="workspaceSwitching">
        <datalist id="recent-workspaces">
          <option v-for="item in workspaceState?.recent ?? []" :key="item.path" :value="item.path">
            {{ item.name }}
          </option>
        </datalist>
        <button type="submit" :disabled="workspaceSwitching || !workspacePath.trim()">
          {{ workspaceSwitching ? '切换中…' : '确认切换' }}
        </button>
        <small>仅支持本机已存在的绝对目录；任务运行时不能切换。</small>
      </form>
    </section>
    <button class="new-task-button" :disabled="disabled" type="button" @click="$emit('newTask')">
      <span aria-hidden="true">＋</span> 新建会话
    </button>
    <section v-if="historyItems.length" class="history-list" aria-labelledby="history-title">
      <span id="history-title" class="eyebrow">历史</span>
      <button v-for="item in historyItems" :key="item.id" type="button"
        :aria-current="item.id === selectedId ? 'page' : undefined"
        @click="$emit('select', item.id)">
        <span class="history-title" :title="item.title">{{ item.title }}</span>
        <small>{{ item.last_task_status || 'EMPTY' }} · {{ item.task_count }} 次任务</small>
      </button>
      <button v-if="hasMore" type="button" :disabled="loading" @click="$emit('loadMore')">
        {{ loading ? '加载中…' : '加载更多' }}
      </button>
    </section>
    <p v-else-if="loading" class="sidebar-note" role="status">正在加载历史…</p>
    <p v-else class="sidebar-note">尚无历史会话</p>
    <div class="sidebar-spacer" />
    <button class="text-button" type="button" @click="$emit('reconnect')">重新连接后端</button>
    <p class="sidebar-note">单用户 · 单活动工作区 · 单活动任务</p>
  </aside>
</template>
