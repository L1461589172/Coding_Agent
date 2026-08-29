<script setup lang="ts">
import type { ComposerIntent } from '../thread/types'

const props = withDefaults(
  defineProps<{
    disabled: boolean
    busy?: boolean
    sessionId?: string
  }>(),
  {
    busy: false,
    sessionId: undefined,
  },
)

const prompt = defineModel<string>({
  required: true,
})

const emit = defineEmits<{
  submit: [intent: ComposerIntent]
}>()

function submit() {
  const value = prompt.value.trim()

  if (props.disabled || !value) {
    return
  }

  if (props.sessionId) {
    emit('submit', {
      kind: 'follow_up',
      sessionId: props.sessionId,
      prompt: value,
    })

    return
  }

  emit('submit', {
    kind: 'new_task',
    prompt: value,
  })
}

function onKeydown(event: KeyboardEvent) {
  /*
   * Enter          -> 提交
   * Shift + Enter  -> 换行
   *
   * isComposing 用于防止中文输入法
   * 确认候选词时误提交。
   */
  if (
    event.key === 'Enter' &&
    !event.shiftKey &&
    !event.isComposing
  ) {
    event.preventDefault()
    submit()
  }
}
</script>

<template>
  <form
    class="composer"
    @submit.prevent="submit"
  >
    <label
      class="sr-only"
      for="task-prompt"
    >
      描述编程任务
    </label>

    <textarea
      id="task-prompt"
      v-model="prompt"
      :disabled="disabled"
      maxlength="8000"
      rows="2"
      placeholder="让 Coding Agent 修改、调试或解释代码…"
      @keydown="onKeydown"
    />

    <div class="composer-footer">
      <div class="composer-meta">
        <span
          v-if="busy"
          class="composer-busy"
          role="status"
        >
          Agent 正在执行
        </span>

        <span v-else>
          Enter 提交 · Shift + Enter 换行
        </span>

        <span
          v-if="prompt.length > 7000"
          class="composer-count"
        >
          {{ prompt.length.toLocaleString() }} / 8,000
        </span>
      </div>

      <button
        class="composer-submit"
        type="submit"
        :disabled="disabled || !prompt.trim()"
        :aria-label="sessionId ? '继续会话' : '开始新会话'"
        :title="sessionId ? '继续会话' : '开始新会话'"
      >
        <span aria-hidden="true">↑</span>
      </button>
    </div>
  </form>
</template>