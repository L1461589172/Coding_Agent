// Optional browser QA; Playwright is a test-only dependency, not part of the app.
// Start the backend and frontend first. Then: node scripts/smoke_browser.cjs
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')
const { chromium } = require('playwright')

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1365, height: 1000 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto('http://127.0.0.1:5173')
    await page.getByText('demo_workspace', { exact: true }).waitFor()
    assert.equal(await page.locator('.tool-list li').count(), 6)
    await page.getByLabel('描述编程任务').fill('基础框架检查，不执行任何文件修改')
    await page.getByRole('button', { name: '开始任务' }).click()
    await page.locator('.result-panel').getByText(/NOT_IMPLEMENTED/).waitFor()
    assert.equal(await page.locator('.timeline .event').count(), 3)
    assert.equal(await page.locator('.status-pill').textContent(), '未完成')
    assert.equal(await page.getByRole('button', { name: '开始任务' }).isEnabled(), true)
    await page.reload()
    await page.locator('.result-panel').getByText(/NOT_IMPLEMENTED/).waitFor()
    assert.equal(await page.locator('.timeline .event').count(), 3)
    assert.match(await page.locator('.info-banner').textContent(), /已恢复浏览器刷新前的任务/)
    const output = path.resolve('output/qa')
    fs.mkdirSync(output, { recursive: true })
    await page.screenshot({ path: path.join(output, 'framework-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: path.join(output, 'framework-mobile.png'), fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(errors, [])
    console.log('Browser smoke passed: metadata, submit, refresh restore, 3 SSE events, NOT_IMPLEMENTED, mobile layout.')
  } finally {
    await browser.close()
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
