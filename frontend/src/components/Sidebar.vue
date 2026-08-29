<script setup lang="ts">
import type { Metadata } from '../types'

export interface HistoryItem {
  id: string
  title: string
  status: string
}

withDefaults(defineProps<{
  metadata: Metadata | null
  disabled?: boolean
  historyItems?: HistoryItem[]
  selectedId?: string
}>(), {
  disabled: false,
  historyItems: () => [],
  selectedId: undefined,
})

defineEmits<{
  newTask: []
  reconnect: []
  select: [id: string]
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
      <span aria-hidden="true">＋</span> 开始新任务
    </button>
    <section v-if="historyItems.length" class="history-list" aria-labelledby="history-title">
      <span id="history-title" class="eyebrow">历史</span>
      <button v-for="item in historyItems" :key="item.id" type="button"
        :aria-current="item.id === selectedId ? 'page' : undefined"
        @click="$emit('select', item.id)">
        <span>{{ item.title }}</span><small>{{ item.status }}</small>
      </button>
    </section>
    <div class="sidebar-spacer" />
    <button class="text-button" type="button" @click="$emit('reconnect')">重新连接后端</button>
    <p class="sidebar-note">单用户 · 单工作区 · 单活动任务</p>
  </aside>
</template>
