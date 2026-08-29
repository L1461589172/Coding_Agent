// Optional browser QA; Playwright is a test-only dependency, not part of the app.
// Start the backend and frontend first. Then: node scripts/smoke_browser.cjs
const assert = require('node:assert/strict')
const { createRequire } = require('node:module')
const path = require('node:path')
const fs = require('node:fs')
const frontendRequire = createRequire(path.resolve('frontend/package.json'))
const { chromium } = frontendRequire('playwright')

const timestamp = '2026-08-29T08:00:00Z'
const metadata = {
  workspace: 'demo_workspace', mode: 'agent', agent_ready: true,
  tools: ['list_files', 'read_file', 'search_text', 'write_file', 'replace_in_file', 'run_command'],
  tool_statuses: Object.fromEntries(
    ['list_files', 'read_file', 'search_text', 'write_file', 'replace_in_file', 'run_command']
      .map((tool) => [tool, 'ready']),
  ),
}

function task(id, status, summary = null) {
  return {
    id, prompt: '修复示例并运行测试', status, mode: 'agent', created_at: timestamp,
    started_at: timestamp, finished_at: status === 'COMPLETED' ? timestamp : null,
    result: status === 'COMPLETED' ? '修复完成，测试通过。' : null,
    error: null, summary,
  }
}

function event(id, type, payload, step = 1) {
  return { id: String(id), task_id: 'mock-task', type, timestamp, step, payload }
}

const summary = {
  files_read: ['calculator.py'], files_changed: ['calculator.py'],
  commands: [{ command: 'pytest -q', ok: true, exit_code: 0, timed_out: false, cleanup_ok: true, duration_ms: 18, error_code: null }],
  verification: { kind: 'pytest', command: 'pytest -q', passed: true, exit_code: 0, output_excerpt: '2 passed', output_truncated: false },
  tool_calls: 2, decision_steps: 2, error_codes: [], duration_ms: 42,
}

const agentEvents = [
  event(1, 'task_started', { mode: 'agent' }, 0),
  event(2, 'assistant_message', { message: '检查实现并进行最小修改。', mode: 'agent' }),
  event(3, 'tool_started', { call_id: 'edit', tool: 'replace_in_file', arguments: { path: 'calculator.py' }, synthetic: false }),
  event(4, 'file_changed', { call_id: 'edit', tool: 'replace_in_file', path: 'calculator.py', action: 'modified', bytes_before: 20, bytes_after: 38, sha256_before: 'a', sha256_after: 'b', diff: '- return a / b\n+ return None if b == 0 else a / b', diff_truncated: false, cleanup_pending: false }),
  event(5, 'tool_finished', { call_id: 'edit', tool: 'replace_in_file', ok: true, error_code: null, error_message: null, truncated: false, duration_ms: 5, result: { ok: true, output: {}, error_code: null, error_message: null, truncated: false }, synthetic: false }),
  event(6, 'tool_started', { call_id: 'test', tool: 'run_command', arguments: { command: 'pytest -q' }, synthetic: false }, 2),
  event(7, 'command_finished', { call_id: 'test', ok: true, error_code: null, command: 'pytest -q', exit_code: 0, termination_reason: 'exited', timed_out: false, cleanup_ok: true, stdout: '2 passed', stderr: '', stdout_truncated: false, stderr_truncated: false, duration_ms: 18 }, 2),
  event(8, 'tool_finished', { call_id: 'test', tool: 'run_command', ok: true, error_code: null, error_message: null, truncated: false, duration_ms: 18, result: { ok: true, output: {}, error_code: null, error_message: null, truncated: false }, synthetic: false }, 2),
  event(9, 'assistant_message', { message: '修复完成，测试通过。', mode: 'agent' }, 3),
  event(10, 'task_completed', { result: '修复完成，测试通过。' }, 3),
]

async function json(route, body, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function mockMetadata(page) {
  await page.route('**/api/meta', (route) => json(route, metadata))
}

async function runMockAgentFlows(browser) {
  const runningPage = await browser.newPage({ viewport: { width: 1000, height: 800 } })
  await mockMetadata(runningPage)
  await runningPage.route('**/api/tasks', (route) => json(route, task('running-task', 'PENDING')))
  let releaseStream
  const streamGate = new Promise((resolve) => { releaseStream = resolve })
  await runningPage.route('**/api/tasks/running-task/events**', async (route) => {
    await streamGate
    await route.fulfill({ status: 204 })
  })
  await runningPage.goto('http://127.0.0.1:5173')
  await runningPage.getByLabel('描述编程任务').fill('长任务')
  await runningPage.locator('.composer').getByRole('button', { name: '开始新任务' }).click()
  await runningPage.locator('.run-status').getByText('PENDING').waitFor()
  assert.equal(await runningPage.locator('.composer textarea').isDisabled(), true)
  assert.equal(await runningPage.locator('.new-task-button').isDisabled(), true)
  releaseStream()
  await runningPage.close()

  const completedPage = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  await mockMetadata(completedPage)
  await completedPage.route('**/api/tasks', (route) => json(route, task('mock-task', 'PENDING')))
  await completedPage.route('**/api/tasks/mock-task', (route) => json(route, task('mock-task', 'COMPLETED', summary)))
  let streams = 0
  await completedPage.route('**/api/tasks/mock-task/events**', async (route) => {
    streams += 1
    if (streams === 1) return route.fulfill({ status: 410 })
    const body = agentEvents.map((item) => `id: ${item.id}\ndata: ${JSON.stringify(item)}\n\n`).join('')
    return route.fulfill({ status: 200, contentType: 'text/event-stream', body })
  })
  await completedPage.goto('http://127.0.0.1:5173')
  await completedPage.getByLabel('描述编程任务').fill('修复示例并运行测试')
  await completedPage.locator('.composer').getByRole('button', { name: '开始新任务' }).click()
  await completedPage.locator('.task-summary').getByText('测试通过', { exact: false }).first().waitFor()
  assert.equal(await completedPage.locator('.activity-item').count(), 2)
  assert.equal(await completedPage.locator('.activity-details').count(), 2)
  assert.match(await completedPage.locator('.history-window-note').textContent(), /较早的活动事件已过期/)
  assert.match(await completedPage.locator('.task-summary').textContent(), /calculator.py/)
  assert.match(await completedPage.locator('.task-summary').textContent(), /pytest -q/)
  await completedPage.getByText('文件变更 · calculator.py').click()
  await completedPage.getByText('pytest -q', { exact: false }).first().click()
  assert.equal(await completedPage.locator('details[open]').count(), 2)
  await completedPage.close()

  const terminalPage = await browser.newPage()
  await terminalPage.addInitScript(() => localStorage.setItem(
    'coding-agent:recent-context:v1', JSON.stringify({ version: 1, taskId: 'terminal-task' }),
  ))
  await mockMetadata(terminalPage)
  await terminalPage.route('**/api/tasks/terminal-task', (route) => json(route, task('terminal-task', 'COMPLETED', summary)))
  await terminalPage.route('**/api/tasks/terminal-task/events**', (route) => route.fulfill({ status: 204 }))
  await terminalPage.goto('http://127.0.0.1:5173')
  await terminalPage.locator('.task-summary').waitFor()
  assert.equal(await terminalPage.locator('.error-banner').count(), 0)
  await terminalPage.close()

  const missingPage = await browser.newPage()
  await missingPage.addInitScript(() => localStorage.setItem(
    'coding-agent:recent-context:v1', JSON.stringify({ version: 1, taskId: 'missing-task' }),
  ))
  await mockMetadata(missingPage)
  await missingPage.route('**/api/tasks/missing-task', (route) => json(route, { detail: 'Not found' }, 404))
  await missingPage.goto('http://127.0.0.1:5173')
  await missingPage.getByRole('alert').getByText(/历史已清空/).waitFor()
  assert.equal(await missingPage.locator('.thread-empty').count(), 1)
  await missingPage.close()
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1365, height: 1000 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto('http://127.0.0.1:5173')
    await page.locator('.workspace-name').getByText('demo_workspace', { exact: true }).waitFor()
    assert.equal(await page.locator('.history-list').count(), 0)
    assert.equal(await page.locator('.conversation-thread').count(), 1)
    assert.match(await page.locator('.thread-empty').textContent(), /准备好开始一个任务/)
    await page.keyboard.press('Tab')
    assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'BUTTON')
    await page.getByLabel('描述编程任务').fill('基础框架检查，不执行任何文件修改')
    await page.locator('.composer').getByRole('button', { name: '开始新任务' }).click()
    await page.locator('.task-summary').getByText(/NOT_IMPLEMENTED/).waitFor()
    assert.equal(await page.locator('.task-run').count(), 1)
    assert.equal(await page.locator('.recovery-item').count(), 1)
    assert.equal(await page.locator('.activity-item').count(), 0)
    assert.equal(await page.locator('.run-status').textContent(), 'FAILED')
    assert.match(await page.locator('.task-summary').textContent(), /0工具调用/)
    assert.equal(await page.locator('.new-task-button').isEnabled(), true)
    assert.equal(await page.locator('.composer textarea').isEnabled(), true)
    await page.reload()
    await page.locator('.task-summary').getByText(/NOT_IMPLEMENTED/).waitFor()
    assert.equal(await page.locator('.task-run').count(), 1)
    assert.match(await page.locator('.info-banner').textContent(), /已恢复刷新前的任务/)
    const output = path.resolve('output/qa')
    fs.mkdirSync(output, { recursive: true })
    await page.screenshot({ path: path.join(output, 'm5-framework-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: path.join(output, 'm5-framework-mobile.png'), fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.locator('.new-task-button').focus()
    assert.equal(await page.locator('.new-task-button').evaluate((node) => node.matches(':focus-visible')), true)
    assert.deepEqual(errors, [])
    await runMockAgentFlows(browser)
    console.log('Browser smoke passed: M5 failed/running/completed, activity attachments, 410/404/204, refresh, focus, and mobile layout.')
  } finally {
    await browser.close()
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
