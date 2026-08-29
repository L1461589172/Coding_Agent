const assert = require('node:assert/strict')
const { createRequire } = require('node:module')
const path = require('node:path')

const frontendRequire = createRequire(path.resolve('frontend/package.json'))
const { chromium } = frontendRequire('playwright')
const timestamp = '2026-08-29T08:00:00Z'
const sessionId = '00000000-0000-4000-8000-000000000001'

function task(id, ordinal, status = 'COMPLETED') {
  return {
    id, session_id: sessionId, ordinal, prompt: `第 ${ordinal} 轮任务`, status, mode: 'agent',
    created_at: timestamp, started_at: timestamp,
    finished_at: status === 'COMPLETED' ? timestamp : null,
    result: status === 'COMPLETED' ? `第 ${ordinal} 轮完成` : null,
    error: null,
    summary: status === 'COMPLETED' ? {
      files_read: ['calculator.py'], files_changed: [], commands: [], verification: null,
      tool_calls: 1, decision_steps: 1, error_codes: [], duration_ms: 10,
    } : null,
  }
}

function session(count = 2) {
  return {
    id: sessionId, title: '历史会话', created_at: timestamp, updated_at: timestamp,
    task_count: count, last_task_id: `task-${count}`, last_task_status: 'COMPLETED',
    history_incomplete: false,
  }
}

async function json(route, body, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
    page.on('dialog', (dialog) => dialog.accept())
    let tasks = [task('task-1', 1), task('task-2', 2)]
    let deleted = false

    await page.route('**/api/meta', (route) => json(route, {
      workspace: 'demo_workspace', mode: 'agent', agent_ready: true,
      tools: ['read_file'], tool_statuses: { read_file: 'ready' },
    }))
    await page.route('**/api/sessions?**', (route) => json(route, {
      items: deleted ? [] : [session(tasks.length)], next_cursor: null,
    }))
    await page.route(`**/api/sessions/${sessionId}/tasks?**`, (route) => json(route, {
      items: [...tasks].reverse(), next_before_ordinal: null,
    }))
    await page.route(`**/api/sessions/${sessionId}/tasks`, async (route) => {
      const created = task('task-3', 3, 'PENDING')
      tasks.push(created)
      await json(route, created, 202)
    })
    await page.route('**/api/tasks/task-3/events**', async (route) => {
      const completed = {
        id: '1', task_id: 'task-3', type: 'task_completed', timestamp, step: 1,
        payload: { result: '第 3 轮完成' },
      }
      await route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: `id: 1\ndata: ${JSON.stringify(completed)}\n\n`,
      })
    })
    await page.route('**/api/tasks/task-3', (route) => {
      tasks[2] = task('task-3', 3)
      return json(route, tasks[2])
    })
    await page.route(`**/api/sessions/${sessionId}`, async (route) => {
      if (route.request().method() === 'DELETE') {
        deleted = true
        return route.fulfill({ status: 204 })
      }
      return json(route, session(tasks.length))
    })
    await page.route('**/api/tasks/task-*/events**', (route) => route.fulfill({ status: 204 }))

    await page.goto(`http://127.0.0.1:5173/?session=${sessionId}`)
    await page.locator('.task-run').nth(1).waitFor()
    assert.equal(await page.locator('.task-run').count(), 2)
    assert.equal(await page.locator('.history-list button[aria-current="page"]').count(), 1)
    await page.getByLabel('描述编程任务').fill('继续检查')
    await page.locator('.composer').getByRole('button', { name: '继续会话' }).click()
    await page.locator('.task-run').nth(2).waitFor()
    assert.equal(await page.locator('.task-run').count(), 3)
    assert.match(page.url(), new RegExp(`session=${sessionId}`))

    await page.setViewportSize({ width: 390, height: 844 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.getByRole('button', { name: '删除会话' }).click()
    await page.locator('.thread-empty').waitFor()
    assert.equal(deleted, true)
    assert.equal(new URL(page.url()).searchParams.has('session'), false)
    console.log('Browser smoke passed: M6 history, multi-TaskRun follow-up, URL, delete, and 390px layout.')
  } finally {
    await browser.close()
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
