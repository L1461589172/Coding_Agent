<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ submit: [prompt: string] }>()
const prompt = ref('')
</script>

<template>
  <form class="task-form" @submit.prevent="prompt.trim() && emit('submit', prompt.trim())">
    <label for="task-prompt">描述编程任务</label>
    <textarea id="task-prompt" v-model="prompt" :disabled="disabled" maxlength="8000" rows="4"
      placeholder="例如：修复 divide 的除零行为，并确保测试通过。当前版本仅检查任务链路，不执行此任务。" />
    <div class="form-footer">
      <span>当前仅联调 API 与事件流，不调用模型。</span>
      <button type="submit" :disabled="disabled || !prompt.trim()">{{ disabled ? '处理中…' : '检查任务链路' }}</button>
    </div>
  </form>
</template>
