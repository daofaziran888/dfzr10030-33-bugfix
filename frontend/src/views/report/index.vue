<template>
  <section class="page" data-module="report">
    <header class="page-head">
      <div><h2>采集报告</h2><p class="page-desc">维护采集报告，围绕报告编号、采集源、统计周期、总采集量做登记、筛选与状态流转。</p></div>
    </header>
    <div class="analysis-summary">
      <article v-for="m in summaryMetrics" :key="m.label" class="analysis-card" data-testid="kpi-card">
        <span style="font-size:12px;color:var(--muted)">{{ m.label }}</span>
        <strong style="font-size:22px;display:block">{{ m.value }}</strong>
        <span :class="m.trend > 0 ? 'trend-up' : 'trend-down'" style="font-size:12px">{{ m.trend > 0 ? '↑' : '↓' }}{{ Math.abs(m.trend) }}%</span>
      </article>
      <article class="analysis-card" data-testid="kpi-retry-pending">
        <span style="font-size:12px;color:var(--muted)">待核对失败请求</span>
        <strong style="font-size:22px;display:block">{{ retryPending }}</strong>
        <span style="font-size:12px;color:var(--muted)">来自API调用重试台账</span>
      </article>
    </div>
    <form class="analysis-form" @submit.prevent="runAnalysis">
      <label v-for="field in paramFields" :key="field"><span>{{ field }}</span>
        <select v-if="field.includes('方法')||field.includes('策略')||field.includes('粒度')" v-model="params[field]"><option v-for="o in options[field]" :key="o" :value="o">{{ o }}</option></select>
        <input v-else v-model="params[field]" :placeholder="`请输入${field}`" />
      </label>
      <button class="btn primary" type="submit" data-testid="run-analysis">运行分析</button>
    </form>
    <div v-if="chartData.length" class="analysis-chart">
      <div v-for="(bar, i) in chartData" :key="i" class="analysis-bar" :style="{ height: barHeight(bar.value) + 'px' }"><span>{{ bar.label }}</span></div>
    </div>
    <table class="data-table" v-if="results.length">
      <thead><tr><th v-for="c in resultColumns" :key="c">{{ c }}</th></tr></thead>
      <tbody><tr v-for="row in results" :key="row.id"><td v-for="c in resultColumns" :key="c">{{ row[c] ?? '—' }}</td></tr></tbody>
    </table>
    <p v-if="!results.length && !loading" style="text-align:center;color:var(--muted)">请配置参数后运行分析</p>

    <section class="retry-review" data-testid="retry-review">
      <header class="page-head">
        <div>
          <h3>失败接口批次（API调用重试台账同步）</h3>
          <p class="page-desc">跟随重试台账状态变化实时更新；待核对清单列出仍需运维处理的失败请求。</p>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr><th>客户端编号</th><th>归属批次</th><th>失败接口数</th><th>接口列表</th><th>待重试</th><th>重试中</th><th>重试成功</th><th>重试失败</th><th>批次状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="batch in retryBatches" :key="`${batch['客户端编号']}-${batch['归属批次']}`" data-testid="retry-batch-row">
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
          <tr v-if="!retryBatches.length">
            <td colspan="9" class="empty-state">暂无失败接口批次</td>
          </tr>
        </tbody>
      </table>
      <h3>待核对清单</h3>
      <table class="data-table">
        <thead>
          <tr><th>台账编号</th><th>请求编号</th><th>客户端编号</th><th>接口名称</th><th>归属批次</th><th>重试状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in retryPendingList" :key="String(item['台账编号'])" data-testid="retry-pending-row">
            <td>{{ item['台账编号'] }}</td>
            <td>{{ item['请求编号'] }}</td>
            <td>{{ item['客户端编号'] }}</td>
            <td>{{ item['接口名称'] }}</td>
            <td>{{ item['归属批次'] }}</td>
            <td>{{ item['重试状态'] }}</td>
          </tr>
          <tr v-if="!retryPendingList.length">
            <td colspan="6" class="empty-state">没有待核对的失败请求</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '@/api/client'
const ENDPOINT = '/api/report'
const summaryMetrics = ref<{label:string;value:number;trend:number}[]>([])
const results = ref<any[]>([]); const chartData = ref<{label:string;value:number}[]>([])
const loading = ref(false)
const params = ref<Record<string,string>>({})
const paramFields = ["报告编号", "采集源", "统计周期", "总采集量", "成功量", "失败量", "平均耗秒", "生成时间"].filter((f: string) => !['编号','名称','版本'].includes(f)).slice(0, 4)
const options: Record<string,string[]> = { '统计粒度': ['按日','按周','按月'], '分组字段': ['全量','按类型','按区域'], '比较方法': ['环比','同比','绝对值'], '时间范围': ['最近7天','最近30天','最近90天'] }
const resultColumns = computed(() => ["报告编号", "采集源", "统计周期", "总采集量", "成功量", "失败量", "平均耗秒", "生成时间"].slice(0, 5))
const retryPending = ref(0)
const retryBatches = ref<Record<string, string | number | string[]>[]>([])
const retryPendingList = ref<Record<string, string | number>[]>([])
function barHeight(v: number) { const max = Math.max(...chartData.value.map(d => d.value), 1); return Math.max(10, (v / max) * 140) }
async function fetchSummary() { try { const res = await request(`${ENDPOINT}/summary`); summaryMetrics.value = (await res.json()).metrics || [] } catch(e) {} }
async function fetchRetryReview() {
  try {
    const res = await request(`${ENDPOINT}/retry_review`)
    if (!res.ok) return
    const data = await res.json()
    retryPending.value = data['待核对数'] ?? 0
    retryBatches.value = data['失败接口批次'] ?? []
    retryPendingList.value = data['待核对清单'] ?? []
  } catch(e) {}
}
async function runAnalysis() {
  loading.value = true
  try { const res = await request(`${ENDPOINT}/run`, { method: 'POST', body: JSON.stringify({ values: params.value }) }); const data = await res.json(); results.value = data.items || []; chartData.value = (data.items || []).map((r: any) => ({ label: Object.values(r)[0] as string, value: Object.values(r).filter(v => typeof v === 'number')[0] as number || 0 })).slice(0, 6) } catch(e) { results.value = [] }
  loading.value = false
}
onMounted(() => { void fetchSummary(); void fetchRetryReview() })
</script>
<style scoped>
.retry-review {
  margin-top: 24px;
  border-top: 2px solid var(--border);
  padding-top: 8px;
}
.retry-review h3 {
  font-size: 14px;
  margin: 12px 0 8px;
}
</style>
