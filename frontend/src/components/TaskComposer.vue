<script setup lang="ts">
import type { ComposerIntent } from '../thread/types'

const props = withDefaults(defineProps<{
  disabled: boolean
  busy?: boolean
  sessionId?: string
}>(), { busy: false, sessionId: undefined })
const prompt = defineModel<string>({ required: true })
const emit = defineEmits<{ submit: [intent: ComposerIntent] }>()

function submit() {
  const value = prompt.value.trim()
  if (!props.disabled && value) {
    emit('submit', props.sessionId
      ? { kind: 'follow_up', sessionId: props.sessionId, prompt: value }
      : { kind: 'new_task', prompt: value })
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <label class="sr-only" for="task-prompt">描述编程任务</label>
    <textarea id="task-prompt" v-model="prompt" :disabled="disabled" maxlength="8000" rows="3"
      placeholder="描述你希望 Agent 完成的编程任务…" />
    <div class="composer-footer">
      <span>{{ prompt.length.toLocaleString() }} / 8,000</span>
      <span v-if="busy" class="composer-busy" role="status">当前任务正在执行</span>
      <button type="submit" :disabled="disabled || !prompt.trim()">
        {{ busy ? '处理中…' : sessionId ? '继续会话' : '开始新会话' }}
      </button>
    </div>
  </form>
</template>
