<script setup lang="ts">
import type { Metadata, SessionListItem } from '../types'

withDefaults(defineProps<{
  metadata: Metadata | null
  disabled?: boolean
  historyItems?: SessionListItem[]
  selectedId?: string
  loading?: boolean
  hasMore?: boolean
}>(), {
  disabled: false,
  historyItems: () => [],
  selectedId: undefined,
  loading: false,
  hasMore: false,
})

defineEmits<{
  newTask: []
  reconnect: []
  select: [id: string]
  loadMore: []
}>()
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
      <p class="readiness" :class="{ ready: metadata?.agent_ready }">
        <span aria-hidden="true">{{ metadata?.agent_ready ? '●' : '○' }}</span>
        {{ metadata?.agent_ready ? 'Agent Ready' : '模型未配置' }}
      </p>
    </section>
    <button class="new-task-button" :disabled="disabled" type="button" @click="$emit('newTask')">
      <span aria-hidden="true">＋</span> 新建会话
    </button>
    <section v-if="historyItems.length" class="history-list" aria-labelledby="history-title">
      <span id="history-title" class="eyebrow">历史</span>
      <button v-for="item in historyItems" :key="item.id" type="button"
        :aria-current="item.id === selectedId ? 'page' : undefined"
        @click="$emit('select', item.id)">
        <span>{{ item.title }}</span>
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
    <p class="sidebar-note">单用户 · 单工作区 · 单活动任务</p>
  </aside>
</template>
