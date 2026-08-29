<script setup lang="ts">
import type { Task } from '../types'

defineProps<{ task: Task }>()

function duration(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined) return '—'
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`
  return `${(milliseconds / 1000).toFixed(1)} s`
}
</script>

<template>
  <section class="task-summary" :class="task.status.toLowerCase()" aria-labelledby="summary-title">
    <div class="summary-heading">
      <div>
        <span class="eyebrow">任务结果</span>
        <h3 id="summary-title">{{ task.status === 'COMPLETED' ? '已完成' : '任务未完成' }}</h3>
      </div>
      <span class="summary-status">{{ task.status }}</span>
    </div>
    <div v-if="task.result" class="summary-narrative">
      <span class="summary-label">Agent 回复</span>
      <p>{{ task.result }}</p>
    </div>
    <div v-if="task.error" class="summary-error" role="status">
      <code>{{ task.error.code }}</code><span>{{ task.error.message }}</span>
    </div>
    <div v-if="task.summary" class="summary-facts">
      <div class="summary-metrics">
        <div><strong>{{ task.summary.tool_calls }}</strong><span>工具调用</span></div>
        <div><strong>{{ task.summary.decision_steps }}</strong><span>决策轮次</span></div>
        <div><strong>{{ duration(task.summary.duration_ms) }}</strong><span>总耗时</span></div>
      </div>
      <div v-if="task.summary.files_changed.length" class="summary-block">
        <span class="summary-label">真实文件变更</span>
        <ul><li v-for="path in task.summary.files_changed" :key="path"><code>{{ path }}</code></li></ul>
      </div>
      <div v-if="task.summary.verification" class="verification"
        :class="task.summary.verification.passed ? 'passed' : 'failed'">
        <strong>{{ task.summary.verification.passed ? '✓ 测试通过' : '✕ 测试未通过' }}</strong>
        <code>{{ task.summary.verification.command }}</code>
        <span>exit {{ task.summary.verification.exit_code ?? '—' }}</span>
        <details v-if="task.summary.verification.output_excerpt">
          <summary>查看测试输出摘录</summary>
          <pre>{{ task.summary.verification.output_excerpt }}</pre>
          <p v-if="task.summary.verification.output_truncated" class="truncation-note">摘录已截断。</p>
        </details>
      </div>
      <div v-if="task.summary.commands.length" class="summary-block">
        <span class="summary-label">执行命令</span>
        <ul class="command-summary-list">
          <li v-for="(command, index) in task.summary.commands" :key="`${index}:${command.command}`">
            <span :class="command.ok ? 'ok-mark' : 'error-mark'">{{ command.ok ? '✓' : '✕' }}</span>
            <code>{{ command.command }}</code>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
