<script setup lang="ts">
import {
  PhCheckCircle,
  PhCircle,
  PhFolder,
  PhFolderPlus,
  PhMagnifyingGlass,
  PhPlus,
  PhRobot,
} from '@phosphor-icons/vue'
import { computed, ref, watch } from 'vue'

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

const recentWorkspaces = computed(() => {
  const current = props.metadata?.workspace_path?.toLowerCase()
  return (props.workspaceState?.recent ?? []).filter(
    (item) => item.path.toLowerCase() !== current,
  )
})

const historyGroups = computed(() => {
  const today = new Date()
  const todayKey = `${today.getFullYear()}-${today.getMonth()}-${today.getDate()}`
  const groups = new Map<string, SessionListItem[]>()

  for (const item of props.historyItems) {
    const date = new Date(item.updated_at)
    const key = Number.isNaN(date.getTime())
      ? '更早'
      : `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}` === todayKey
        ? '今天'
        : '更早'
    groups.set(key, [...(groups.get(key) ?? []), item])
  }

  return ['今天', '更早']
    .filter((label) => groups.has(label))
    .map((label) => ({ label, items: groups.get(label) ?? [] }))
})

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

function switchToRecent(path: string) {
  if (!props.disabled && !props.workspaceSwitching) emit('switchWorkspace', path)
}

function historyTime(value: string) {
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
  <aside class="sidebar" aria-label="工作区导航">
    <div class="sidebar-brand">
      <span class="brand-icon" aria-hidden="true">
        <PhRobot :size="23" weight="duotone" />
      </span>
      <div class="brand-copy">
        <strong>Coding Agent</strong>
        <span>智能编程助手</span>
      </div>
    </div>

    <button class="new-task-button" :disabled="disabled" type="button" @click="$emit('newTask')">
      <PhPlus :size="19" weight="bold" aria-hidden="true" />
      <span>新建任务</span>
      <kbd>Ctrl N</kbd>
    </button>

    <section class="sidebar-section workspace-section" aria-labelledby="workspace-title">
      <h2 id="workspace-title" class="sidebar-section-title">工作区</h2>

      <button class="workspace-row current" type="button" disabled aria-current="true">
        <span class="workspace-icon">
          <PhFolder :size="18" weight="fill" aria-hidden="true" />
        </span>
        <span class="workspace-copy">
          <strong>{{ metadata?.workspace || '尚未连接' }}</strong>
          <small :title="metadata?.workspace_path">
            {{ metadata?.workspace_path || '等待后端连接' }}
          </small>
        </span>
        <PhCheckCircle
          v-if="metadata"
          class="workspace-check"
          :size="18"
          weight="fill"
          aria-label="当前工作区"
        />
      </button>

      <button
        v-for="item in recentWorkspaces.slice(0, 2)"
        :key="item.path"
        class="workspace-row"
        type="button"
        :disabled="disabled || workspaceSwitching"
        @click="switchToRecent(item.path)"
      >
        <span class="workspace-icon">
          <PhFolder :size="18" aria-hidden="true" />
        </span>
        <span class="workspace-copy">
          <strong>{{ item.name }}</strong>
          <small :title="item.path">{{ item.path }}</small>
        </span>
      </button>

      <button
        class="add-workspace-button"
        type="button"
        :disabled="disabled || workspaceSwitching || !metadata"
        :aria-expanded="switcherOpen"
        @click="switcherOpen = !switcherOpen"
      >
        <PhFolderPlus :size="18" aria-hidden="true" />
        {{ switcherOpen ? '取消添加' : '添加工作区' }}
      </button>

      <form v-if="switcherOpen" class="workspace-switcher" @submit.prevent="submitWorkspace">
        <label for="workspace-path">本机绝对路径</label>
        <input
          id="workspace-path"
          v-model="workspacePath"
          type="text"
          list="recent-workspaces"
          autocomplete="off"
          spellcheck="false"
          placeholder="D:\Projects\my-project"
          :disabled="workspaceSwitching"
        >
        <datalist id="recent-workspaces">
          <option v-for="item in workspaceState?.recent ?? []" :key="item.path" :value="item.path">
            {{ item.name }}
          </option>
        </datalist>
        <button type="submit" :disabled="workspaceSwitching || !workspacePath.trim()">
          {{ workspaceSwitching ? '切换中…' : '确认切换' }}
        </button>
        <small>仅支持本机已存在目录；任务运行时不能切换。</small>
      </form>
    </section>

    <section class="sidebar-section history-list" aria-labelledby="history-title">
      <div class="sidebar-section-heading">
        <h2 id="history-title" class="sidebar-section-title">历史会话</h2>
        <PhMagnifyingGlass :size="18" aria-hidden="true" />
      </div>

      <template v-if="historyItems.length">
        <div v-for="group in historyGroups" :key="group.label" class="history-group">
          <span class="history-group-label">{{ group.label }}</span>
          <button
            v-for="item in group.items"
            :key="item.id"
            type="button"
            :aria-current="item.id === selectedId ? 'page' : undefined"
            @click="$emit('select', item.id)"
          >
            <span class="history-title" :title="item.title">{{ item.title }}</span>
            <time :datetime="item.updated_at">{{ historyTime(item.updated_at) }}</time>
          </button>
        </div>
        <button
          v-if="hasMore"
          class="load-more-button"
          type="button"
          :disabled="loading"
          @click="$emit('loadMore')"
        >
          {{ loading ? '加载中…' : '加载更多' }}
        </button>
      </template>
      <p v-else-if="loading" class="sidebar-note" role="status">正在加载历史…</p>
      <p v-else class="sidebar-note">尚无历史会话</p>
    </section>

    <div class="sidebar-spacer" />

    <section
      class="agent-status-card"
      :class="{ offline: !metadata?.agent_ready }"
      aria-label="Agent 状态"
    >
      <PhCircle class="status-dot" :size="10" weight="fill" aria-hidden="true" />
      <div>
        <strong>{{ metadata?.agent_ready ? 'Agent 已就绪' : 'Agent 尚未就绪' }}</strong>
        <small>{{ metadata?.agent_ready ? '所有服务运行正常' : '请检查模型或后端配置' }}</small>
      </div>
    </section>

    <button class="reconnect-button" type="button" @click="$emit('reconnect')">
      重新连接后端
    </button>
  </aside>
</template>
