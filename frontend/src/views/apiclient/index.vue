<template>
  <section class="page" data-module="apiclient">
    <header class="page-head">
      <div>
        <h2>API接入管理管理</h2>
        <p class="page-desc">维护API客户端，围绕客户端编号、接口名称、请求方法、认证凭证做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记API客户端</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出API接入管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无API接入管理数据，可先登记API客户端</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条API接入管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="ledger" data-testid="retry-ledger">
      <header class="page-head">
        <div>
          <h2>API调用重试台账</h2>
          <p class="page-desc">
            失败请求回执按客户端归集生成重试记录；归属批次以数据版本为准（v2 按事件发生时间，v1 兼容旧口径按接收时间），同一请求只保留一条有效重试记录。
          </p>
        </div>
        <div class="page-actions">
          <button class="btn primary" data-testid="open-receipt" type="button" @click="openReceipt">登记失败回执</button>
          <button class="btn" data-testid="rebuild-ledger" type="button" @click="rebuildLedger">重新归集</button>
        </div>
      </header>

      <div class="stat-row">
        <article v-for="item in ledgerStats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>客户端编号</span>
          <select v-model="ledgerFilters['客户端编号']" data-testid="ledger-filter-client">
            <option value="">全部客户端</option>
            <option v-for="code in clientOptions" :key="code" :value="code">{{ code }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>重试状态</span>
          <select v-model="ledgerFilters['重试状态']" data-testid="ledger-filter-status">
            <option value="">全部状态</option>
            <option v-for="status in retryStatuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>来源</span>
          <select v-model="ledgerFilters['来源']" data-testid="ledger-filter-source">
            <option value="">全部来源</option>
            <option v-for="source in sourceOptions" :key="source" :value="source">{{ source }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>数据版本</span>
          <select v-model="ledgerFilters['数据版本']" data-testid="ledger-filter-version">
            <option value="">全部版本</option>
            <option value="v2">v2（事件时间）</option>
            <option value="v1">v1（接收时间·旧口径）</option>
          </select>
        </label>
        <label class="filter-item">
          <span>请求编号</span>
          <input v-model="ledgerKeyword" data-testid="ledger-filter-keyword" placeholder="按请求编号检索" />
        </label>
        <button class="btn" data-testid="ledger-query" type="submit">查询</button>
        <button class="btn ghost" data-testid="ledger-reset" type="button" @click="resetLedgerFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in ledgerRows"
            :key="String(row.id)"
            :data-testid="`ledger-row-${row.id}`"
            :data-status="String(row['重试状态'])"
          >
            <td v-for="column in ledgerColumns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in ledgerActions(row)"
                :key="action"
                class="link"
                type="button"
                :data-testid="`ledger-action-${row.id}-${action}`"
                @click="runLedgerAction(action, row)"
              >
                {{ action }}
              </button>
              <button class="link" type="button" :data-testid="`ledger-diff-${row.id}`" @click="openDiff(row)">差异</button>
            </td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length + 1" class="empty-state">暂无失败请求进入重试台账</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <button class="btn" type="button" data-testid="ledger-prev" :disabled="ledgerPage <= 1" @click="turnLedgerPage(-1)">上一页</button>
        <span>第 {{ ledgerPage }} / {{ ledgerPageCount }} 页 · 共 {{ ledgerTotal }} 条重试记录</span>
        <button class="btn" type="button" data-testid="ledger-next" :disabled="ledgerPage >= ledgerPageCount" @click="turnLedgerPage(1)">下一页</button>
      </div>

      <div class="ledger-panels">
        <article class="panel">
          <h3>待处理清单</h3>
          <table class="data-table">
            <thead>
              <tr><th>台账编号</th><th>请求编号</th><th>客户端编号</th><th>接口名称</th><th>归属批次</th><th>重试状态</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in pendingList" :key="String(item['台账编号'])" data-testid="pending-item">
                <td>{{ item['台账编号'] }}</td>
                <td>{{ item['请求编号'] }}</td>
                <td>{{ item['客户端编号'] }}</td>
                <td>{{ item['接口名称'] }}</td>
                <td>{{ item['归属批次'] }}</td>
                <td>{{ item['重试状态'] }}</td>
              </tr>
              <tr v-if="!pendingList.length">
                <td colspan="6" class="empty-state">没有待处理的重试记录</td>
              </tr>
            </tbody>
          </table>
        </article>
        <article class="panel">
          <h3>失败接口批次汇总</h3>
          <table class="data-table">
            <thead>
              <tr><th>客户端编号</th><th>归属批次</th><th>失败接口数</th><th>接口列表</th><th>待重试</th><th>重试中</th><th>重试成功</th><th>重试失败</th><th>批次状态</th></tr>
            </thead>
            <tbody>
              <tr v-for="batch in batchSummary" :key="`${batch['客户端编号']}-${batch['归属批次']}`" data-testid="batch-item">
                <td>{{ batch['客户端编号'] }}</td>
                <td>{{ batch['归属批次'] }}</td>
                <td>{{ batch['失败接口数'] }}</td>
                <td>{{ (batch['接口列表'] as string[]).join('、') }}</td>
                <td>{{ batch['待重试'] }}</td>
                <td>{{ batch['重试中'] }}</td>
                <td>{{ batch['重试成功'] }}</td>
                <td>{{ batch['重试失败'] }}</td>
                <td>{{ batch['批次状态'] }}</td>
              </tr>
              <tr v-if="!batchSummary.length">
                <td colspan="9" class="empty-state">暂无失败接口批次</td>
              </tr>
            </tbody>
          </table>
        </article>
      </div>

      <footer class="page-foot">
        <span v-if="ledgerMessage" class="ledger-message">{{ ledgerMessage }}</span>
        <span v-if="ledgerError" class="error-text">{{ ledgerError }}</span>
      </footer>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记API客户端</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showReceipt" class="modal-backdrop" data-testid="receipt-modal">
      <form class="modal" @submit.prevent="submitReceipt">
        <h3>登记失败请求回执</h3>
        <label class="create-field">
          <span>请求编号</span>
          <input v-model="receiptValues['请求编号']" data-testid="receipt-请求编号" placeholder="如 REQ-2026-0008" required />
        </label>
        <label class="create-field">
          <span>客户端编号</span>
          <select v-model="receiptValues['客户端编号']" data-testid="receipt-客户端编号" required>
            <option value="" disabled>选择客户端</option>
            <option v-for="code in clientOptions" :key="code" :value="code">{{ code }}</option>
          </select>
        </label>
        <label class="create-field">
          <span>接口名称</span>
          <input v-model="receiptValues['接口名称']" data-testid="receipt-接口名称" required />
        </label>
        <label class="create-field">
          <span>请求方法</span>
          <select v-model="receiptValues['请求方法']" data-testid="receipt-请求方法">
            <option v-for="method in methodOptions" :key="method" :value="method">{{ method }}</option>
          </select>
        </label>
        <label class="create-field">
          <span>事件发生时间</span>
          <input v-model="receiptValues['事件发生时间']" data-testid="receipt-事件发生时间" placeholder="2026-09-01 10:12:00" required />
        </label>
        <label class="create-field">
          <span>接收时间（留空取当前时间）</span>
          <input v-model="receiptValues['接收时间']" data-testid="receipt-接收时间" placeholder="2026-09-01 10:12:30" />
        </label>
        <label class="create-field">
          <span>数据版本</span>
          <select v-model="receiptValues['数据版本']" data-testid="receipt-数据版本">
            <option value="v2">v2（按事件发生时间归批）</option>
            <option value="v1">v1（旧口径：按接收时间归批）</option>
          </select>
        </label>
        <label class="create-field">
          <span>来源</span>
          <select v-model="receiptValues['来源']" data-testid="receipt-来源">
            <option v-for="source in sourceOptions" :key="source" :value="source">{{ source }}</option>
          </select>
        </label>
        <label class="create-field">
          <span>失败原因</span>
          <input v-model="receiptValues['失败原因']" data-testid="receipt-失败原因" placeholder="如 下游接口超时" />
        </label>
        <p v-if="receiptMessage" class="receipt-message" data-testid="receipt-result">{{ receiptMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="closeReceipt">取消</button>
          <button class="btn primary" data-testid="submit-receipt" type="submit" :disabled="registering">
            {{ registering ? '登记中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="diffDetail" class="modal-backdrop" data-testid="diff-modal">
      <div class="modal">
        <h3>口径差异：{{ diffDetail['台账编号'] }}（{{ diffDetail['请求编号'] }}）</h3>
        <dl class="diff-meta">
          <dt>客户端编号</dt><dd>{{ diffDetail['客户端编号'] }}</dd>
          <dt>接口名称</dt><dd>{{ diffDetail['接口名称'] }}</dd>
          <dt>数据版本</dt><dd>{{ diffDetail['数据版本'] }}</dd>
          <dt>重试状态</dt><dd>{{ diffDetail['重试状态'] }}</dd>
          <dt>回执批次</dt><dd>{{ diffDetail['回执批次'] || '—' }}</dd>
          <dt>归属批次</dt><dd>{{ diffDetail['归属批次'] }}（{{ diffDetail['归属依据'] }}）</dd>
        </dl>
        <table class="data-table">
          <thead>
            <tr><th>口径</th><th>时间</th><th>归属批次</th><th>是否采用</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="leg in diffDetail['口径对比']" :key="leg['口径']" :data-testid="`diff-leg-${leg['口径']}`">
              <td>{{ leg['口径'] }}</td>
              <td>{{ leg['时间'] }}</td>
              <td>{{ leg['归属批次'] }}</td>
              <td>{{ leg['是否采用'] ? '是' : '否' }}</td>
              <td>{{ leg['说明'] }}</td>
            </tr>
          </tbody>
        </table>
        <p class="diff-text" data-testid="diff-text">{{ diffDetail['差异'] }}</p>
        <p class="diff-text">冲突处理：{{ diffDetail['冲突处理'] }}</p>
        <div class="page-actions">
          <button class="btn primary" type="button" data-testid="close-diff" @click="diffDetail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type LedgerRow = Record<string, string | number | null> & { id: number }
type BatchRow = Record<string, string | number | string[]>
interface DiffLeg {
  '口径': string
  '时间': string
  '归属批次': string
  '说明': string
  '是否采用': boolean
}
interface DiffDetail {
  '台账编号': string
  '请求编号': string
  '客户端编号': string
  '接口名称': string
  '数据版本': string
  '回执批次': string
  '归属批次': string
  '归属依据': string
  '重试状态': string
  '口径对比': DiffLeg[]
  '差异': string
  '冲突处理': string
}

const ENDPOINT = '/api/apiclient'
const columns = ["客户端编号", "接口名称", "请求方法", "认证凭证", "限流令牌", "重试策略", "超时配置", "启用状态"]
const actions = ["完成配置", "启动接入", "停用接入"]
const statuses = ["待配置", "已配置", "运行中", "已停用"]
const metricNames = ["接入总数", "运行中客户端", "待配置客户端"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

// ---------- API调用重试台账 ----------
const ledgerColumns = ["台账编号", "请求编号", "客户端编号", "接口名称", "归属批次", "归属依据", "数据版本", "来源", "重试状态"]
const retryStatuses = ["待重试", "重试中", "重试成功", "重试失败"]
const sourceOptions = ["实时回执", "迟到回执", "补录回执"]
const methodOptions = ["GET", "POST", "PUT", "DELETE"]
const LEDGER_ACTION_MAP: Record<string, string[]> = {
  "待重试": ["开始重试"],
  "重试中": ["重试成功", "重试失败"],
  "重试失败": ["重新排队", "开始重试"],
  "重试成功": [],
}
const LEDGER_PAGE_SIZE = 5

const ledgerRows = ref<LedgerRow[]>([])
const ledgerTotal = ref(0)
const ledgerPage = ref(1)
const ledgerFilters = ref<Record<string, string>>({ "客户端编号": "", "重试状态": "", "来源": "", "数据版本": "" })
const ledgerKeyword = ref('')
const ledgerMessage = ref('')
const ledgerError = ref('')
const pendingList = ref<Record<string, string | number>[]>([])
const batchSummary = ref<BatchRow[]>([])
const ledgerTotals = ref<Record<string, number>>({ "失败请求": 0, "待处理": 0, "重试中": 0, "重试成功": 0, "重试失败": 0 })
const clientOptions = ref<string[]>([])
const showReceipt = ref(false)
const registering = ref(false)
const receiptValues = ref<Record<string, string>>({})
const receiptMessage = ref('')
const diffDetail = ref<DiffDetail | null>(null)

const ledgerStats = computed(() => [
  { label: "失败请求总数", value: ledgerTotals.value["失败请求"] ?? 0 },
  { label: "待处理", value: ledgerTotals.value["待处理"] ?? 0 },
  { label: "重试中", value: ledgerTotals.value["重试中"] ?? 0 },
  { label: "重试成功", value: ledgerTotals.value["重试成功"] ?? 0 },
  { label: "重试失败", value: ledgerTotals.value["重试失败"] ?? 0 },
])
const ledgerPageCount = computed(() => Math.max(1, Math.ceil(ledgerTotal.value / LEDGER_PAGE_SIZE)))

function ledgerActions(row: LedgerRow): string[] {
  return LEDGER_ACTION_MAP[String(row["重试状态"])] ?? []
}

function ledgerQuery(): string {
  const params = new URLSearchParams()
  for (const [field, value] of Object.entries(ledgerFilters.value)) {
    if (value) params.set(field, value)
  }
  if (ledgerKeyword.value.trim()) params.set("keyword", ledgerKeyword.value.trim())
  params.set("page", String(ledgerPage.value))
  params.set("size", String(LEDGER_PAGE_SIZE))
  return params.toString()
}

async function reloadLedger() {
  ledgerError.value = ''
  try {
    const response = await request(`${ENDPOINT}/retry?${ledgerQuery()}`)
    if (!response.ok) throw new Error('重试台账读取失败')
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
    ledgerTotal.value = payload.total ?? ledgerRows.value.length
  } catch (error) {
    ledgerError.value = error instanceof Error ? error.message : '重试台账读取失败'
  }
  await reloadLedgerSummary()
}

async function reloadLedgerSummary() {
  try {
    const response = await request(`${ENDPOINT}/retry/summary`)
    if (!response.ok) throw new Error('台账汇总读取失败')
    const payload = await response.json()
    pendingList.value = payload.pending_list ?? []
    batchSummary.value = payload.batches ?? []
    ledgerTotals.value = payload.totals ?? ledgerTotals.value
  } catch (error) {
    ledgerError.value = error instanceof Error ? error.message : '台账汇总读取失败'
  }
}

async function loadClientOptions() {
  try {
    const response = await request(`${ENDPOINT}?size=200`)
    if (!response.ok) return
    const payload = await response.json()
    clientOptions.value = (payload.items ?? []).map((item: Row) => String(item["客户端编号"] ?? '')).filter(Boolean)
  } catch {
    clientOptions.value = []
  }
}

function resetLedgerFilters() {
  ledgerFilters.value = { "客户端编号": "", "重试状态": "", "来源": "", "数据版本": "" }
  ledgerKeyword.value = ''
  ledgerPage.value = 1
  void reloadLedger()
}

function turnLedgerPage(step: number) {
  const next = ledgerPage.value + step
  if (next < 1 || next > ledgerPageCount.value) return
  ledgerPage.value = next
  void reloadLedger()
}

async function runLedgerAction(action: string, row: LedgerRow) {
  ledgerError.value = ''
  ledgerMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/retry/${row.id}/actions`, {
      method: 'POST', body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '重试动作未生效')
    ledgerMessage.value = payload.message
    await reloadLedger()
  } catch (error) {
    ledgerError.value = error instanceof Error ? error.message : '重试动作未生效'
  }
}

async function openDiff(row: LedgerRow) {
  ledgerError.value = ''
  try {
    const response = await request(`${ENDPOINT}/retry/${row.id}/diff`)
    if (!response.ok) throw new Error('差异读取失败')
    diffDetail.value = await response.json()
  } catch (error) {
    ledgerError.value = error instanceof Error ? error.message : '差异读取失败'
  }
}

function openReceipt() {
  receiptValues.value = {
    "请求编号": "", "客户端编号": clientOptions.value[0] ?? "", "接口名称": "",
    "请求方法": "GET", "事件发生时间": "", "接收时间": "", "数据版本": "v2",
    "来源": "实时回执", "失败原因": "",
  }
  receiptMessage.value = ''
  showReceipt.value = true
}

function closeReceipt() {
  showReceipt.value = false
}

async function submitReceipt() {
  registering.value = true
  receiptMessage.value = ''
  ledgerError.value = ''
  try {
    const response = await request(`${ENDPOINT}/retry/receipts`, {
      method: 'POST', body: JSON.stringify(receiptValues.value),
    })
    const payload = await response.json()
    if (!payload.ok) {
      // 重复登记等拦截：留在弹窗里说明原因，同时刷新待处理清单
      receiptMessage.value = payload.message || '回执被拦住'
      await reloadLedgerSummary()
      return
    }
    receiptMessage.value = payload.message
    ledgerMessage.value = payload.message
    showReceipt.value = false
    await reloadLedger()
  } catch (error) {
    receiptMessage.value = error instanceof Error ? error.message : '回执登记失败'
  } finally {
    registering.value = false
  }
}

async function rebuildLedger() {
  ledgerError.value = ''
  try {
    const response = await request(`${ENDPOINT}/retry/rebuild`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '重新归集失败')
    ledgerMessage.value = payload.message
    ledgerPage.value = 1
    await reloadLedger()
  } catch (error) {
    ledgerError.value = error instanceof Error ? error.message : '重新归集失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'apiclient.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
    await loadClientOptions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('API接入管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'API接入管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('API客户端列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'API接入管理列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadClientOptions()
  void reloadLedger()
})
</script>

<style scoped>
.ledger {
  margin-top: 24px;
  border-top: 2px solid var(--border);
  padding-top: 8px;
}
.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}
.ledger-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.panel h3 {
  font-size: 14px;
  margin: 0 0 8px;
}
.filter-item select,
.create-field select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  background: #fff;
}
.filter-item select {
  min-width: 140px;
}
.ledger-message {
  color: #15803d;
}
.receipt-message {
  font-size: 12px;
  color: var(--muted);
}
.diff-meta {
  display: grid;
  grid-template-columns: 96px 1fr 96px 1fr;
  gap: 6px 12px;
  font-size: 13px;
  margin: 0 0 12px;
}
.diff-meta dt {
  color: var(--muted);
  font-size: 12px;
}
.diff-meta dd {
  margin: 0;
}
.diff-text {
  font-size: 13px;
  color: var(--muted);
}
</style>
