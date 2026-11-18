import { expect, test } from '@playwright/test'

/**
 * API接入页可达性 + API调用重试台账全链路验收。
 * 覆盖：页面不再被后端404截获、失败请求按客户端归集、来源/版本筛选、
 * 分页定位、口径差异、重复登记拦截、迟到回执归批、重试状态流转、报告页同步。
 * 注意：后端为内存仓库，运行前需重启后端保证种子状态干净。
 */
test('API接入页可达，失败请求归集进入重试台账', async ({ page }) => {
  test.setTimeout(300_000)
  const browserErrors: string[] = []
  page.on('pageerror', e => browserErrors.push(e.message))
  page.on('response', r => { if (r.url().includes('/api/') && r.status() >= 400) browserErrors.push(`${r.status()} ${r.url()}`) })

  // 1. 页面可达：/apiclient 由前端路由渲染，不再被后端 404 截获
  const response = await page.goto('/apiclient')
  expect(response?.status()).toBe(200)
  await expect(page.getByTestId('retry-ledger')).toBeVisible({ timeout: 10000 })

  const ledgerRows = page.locator('tr[data-testid^="ledger-row-"]')

  // 2. 种子回执归集：8 张回执生成 7 条台账（重复回执仅首版保留）
  await expect(ledgerRows).toHaveCount(5) // 每页 5 条
  await expect(page.locator('.pager')).toContainText('共 7 条重试记录')

  // 3. 按客户端筛选失败请求
  await page.getByTestId('ledger-filter-client').selectOption('APIC-0002')
  await page.getByTestId('ledger-query').click()
  await expect(ledgerRows).toHaveCount(2)
  await expect(ledgerRows.first()).toContainText('APIC-0002')

  // 4. 按客户端 + 重试状态筛选
  await page.getByTestId('ledger-filter-status').selectOption('待重试')
  await page.getByTestId('ledger-query').click()
  await expect(ledgerRows).toHaveCount(2)
  await page.getByTestId('ledger-reset').click()
  await expect(ledgerRows).toHaveCount(5)

  // 5. 按来源和版本搜索：旧口径 v1 的迟到回执只有一条
  await page.getByTestId('ledger-filter-source').selectOption('迟到回执')
  await page.getByTestId('ledger-filter-version').selectOption('v1')
  await page.getByTestId('ledger-query').click()
  await expect(ledgerRows).toHaveCount(1)
  await expect(ledgerRows.first()).toContainText('REQ-2026-0004')
  await expect(ledgerRows.first()).toContainText('接收时间')
  await page.getByTestId('ledger-reset').click()

  // 6. 分页定位结果
  await page.getByTestId('ledger-next').click()
  await expect(ledgerRows).toHaveCount(2)
  await expect(page.locator('.pager')).toContainText('第 2 / 2 页')
  await page.getByTestId('ledger-prev').click()
  await expect(ledgerRows).toHaveCount(5)

  // 7. 直接打开差异：迟到回执 REQ-2026-0005 两种口径归属不同批次
  const lateRow = page.locator('tr[data-testid^="ledger-row-"]', { hasText: 'REQ-2026-0005' })
  await lateRow.getByRole('button', { name: '差异' }).click()
  await expect(page.getByTestId('diff-modal')).toBeVisible()
  await expect(page.getByTestId('diff-leg-事件时间')).toContainText('BATCH-APIC-0003-20260901')
  await expect(page.getByTestId('diff-leg-接收时间')).toContainText('BATCH-APIC-0003-20260902')
  await expect(page.getByTestId('diff-text')).toContainText('v2')
  await expect(page.getByTestId('diff-text')).toContainText('事件时间')
  await page.getByTestId('close-diff').click()
  await expect(page.getByTestId('diff-modal')).toHaveCount(0)

  // 8. 重复登记同一请求：仅首版保留，其余拦住
  await page.getByTestId('open-receipt').click()
  await expect(page.getByTestId('receipt-modal')).toBeVisible()
  await page.getByTestId('receipt-请求编号').fill('REQ-2026-0001')
  await page.getByTestId('receipt-客户端编号').selectOption('APIC-0003')
  await page.getByTestId('receipt-接口名称').fill('订单查询接口')
  await page.getByTestId('receipt-事件发生时间').fill('2026-09-01 10:12:00')
  await page.getByTestId('submit-receipt').click()
  await expect(page.getByTestId('receipt-result')).toContainText('重复登记已拦住')
  await page.getByRole('button', { name: '取消' }).click()
  await expect(page.getByTestId('receipt-modal')).toHaveCount(0)

  // 9. 登记新失败回执：同步回写台账并生成待处理清单
  const requestId = `REQ-E2E-${Date.now()}`
  await page.getByTestId('open-receipt').click()
  await page.getByTestId('receipt-请求编号').fill(requestId)
  await page.getByTestId('receipt-客户端编号').selectOption('APIC-0003')
  await page.getByTestId('receipt-接口名称').fill('订单查询接口')
  await page.getByTestId('receipt-事件发生时间').fill('2026-11-18 08:00:00')
  await page.getByTestId('submit-receipt').click()
  await expect(page.getByTestId('receipt-modal')).toHaveCount(0)
  await expect(page.locator('.pager')).toContainText('共 8 条重试记录')
  await expect(page.locator('tr[data-testid="pending-item"]', { hasText: requestId })).toHaveCount(1)

  // 10. 重试状态流转：待重试 → 重试中，非法流转被拦
  const targetRow = page.locator('tr[data-testid^="ledger-row-"]', { hasText: 'REQ-2026-0001' })
  await targetRow.getByRole('button', { name: '开始重试' }).click()
  await expect(page.locator('tr[data-testid^="ledger-row-"]', { hasText: 'REQ-2026-0001' })).toHaveAttribute('data-status', '重试中')

  // 11. 报告页同步显示失败接口批次与待核对内容
  await page.goto('/report')
  await expect(page.getByTestId('retry-review')).toBeVisible({ timeout: 10000 })
  await expect(page.getByTestId('kpi-retry-pending')).toBeVisible()
  expect(await page.locator('tr[data-testid="retry-batch-row"]').count()).toBeGreaterThanOrEqual(3)
  await expect(page.locator('tr[data-testid="retry-batch-row"]', { hasText: 'BATCH-APIC-0003-20260901' })).toHaveCount(1)

  expect(browserErrors).toEqual([])
})
