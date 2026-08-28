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
      placeholder="例如：修复 divide 的除零行为，并运行相关测试。" />
    <div class="form-footer">
      <span>最多 8000 字符；任务运行期间不会重复提交。</span>
      <button type="submit" :disabled="disabled || !prompt.trim()">{{ disabled ? '处理中…' : '开始任务' }}</button>
    </div>
  </form>
</template>
