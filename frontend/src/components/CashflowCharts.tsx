import Plot from 'react-plotly.js'
import type { Config, Data, Layout } from 'plotly.js'
import type {
  CashflowCategoryTotal,
  CashflowSummary,
  InvestmentBucket,
} from '../types'
import { fmtMoney, toWan } from '../format'

const GRID = '#e1e0d9'
const AXIS = '#c3c2b7'
const SECONDARY = '#52514e'
const INK = '#0b0b0b'
const SURFACE = '#fcfcfb'

// Validated categorical order from the shared design palette.
const SERIES = [
  '#2a78d6',
  '#eb6834',
  '#1baf7a',
  '#eda100',
  '#e87ba4',
  '#008300',
  '#6250d6',
  '#e34948',
]

const BUCKET_ORDER: InvestmentBucket[] = [
  'cash',
  'a_share',
  'overseas',
  'gold',
  'bond',
  'other',
]

const BUCKET_LABELS: Record<InvestmentBucket, string> = {
  cash: '现金/货币',
  a_share: 'A股基金',
  overseas: '海外基金',
  gold: '黄金',
  bond: '债券',
  other: '其他',
}

const CONFIG: Partial<Config> = {
  displayModeBar: false,
  responsive: true,
}

function baseLayout(extra: Partial<Layout>): Partial<Layout> {
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'system-ui, sans-serif', size: 11, color: SECONDARY },
    margin: { l: 52, r: 18, t: 8, b: 42 },
    hoverlabel: {
      bgcolor: SURFACE,
      bordercolor: GRID,
      font: { color: INK, size: 11 },
    },
    xaxis: {
      gridcolor: GRID,
      zeroline: false,
      linecolor: AXIS,
      tickfont: { size: 10 },
    },
    yaxis: {
      gridcolor: GRID,
      zeroline: false,
      linecolor: AXIS,
      tickfont: { size: 10 },
    },
    ...extra,
  }
}

function moneyAxis(title: string): Partial<Layout['yaxis']> {
  return {
    title: { text: title, font: { size: 10, color: SECONDARY } },
    ticksuffix: '万',
  }
}

function monthAxis(): Partial<Layout['xaxis']> {
  return { type: 'category', tickangle: -35 }
}

export function MonthlyFlowChart({ summary }: { summary: CashflowSummary }) {
  if (summary.months.length === 0) return null
  const x = summary.months.map((month) => month.month)
  const traces: Data[] = [
    {
      type: 'bar',
      name: '收入',
      x,
      y: summary.months.map((month) => toWan(month.income)),
      customdata: summary.months.map((month) => fmtMoney(month.income)),
      marker: { color: SERIES[0], line: { color: SURFACE, width: 1 } },
      hovertemplate: '%{x}<br>收入 %{customdata}<extra></extra>',
    },
    {
      type: 'bar',
      name: '支出',
      x,
      y: summary.months.map((month) => toWan(month.expense)),
      customdata: summary.months.map((month) => fmtMoney(month.expense)),
      marker: { color: SERIES[1], line: { color: SURFACE, width: 1 } },
      hovertemplate: '%{x}<br>支出 %{customdata}<extra></extra>',
    },
  ]
  return (
    <section className="card cashflow-chart-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">每月收入与支出</h3>
          <p className="card-sub">今日购买力；投资买入和内部转账不计入支出。</p>
        </div>
      </div>
      <Plot
        data={traces}
        layout={baseLayout({
          barmode: 'group',
          bargap: 0.28,
          bargroupgap: 0.08,
          xaxis: monthAxis(),
          yaxis: moneyAxis('万元'),
          legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 10 } },
        })}
        config={CONFIG}
        style={{ width: '100%', height: 300 }}
        useResizeHandler
      />
    </section>
  )
}

export function SavingsRateChart({ summary }: { summary: CashflowSummary }) {
  const points = summary.months
    .map((month) => ({
      month: month.month,
      rate: month.savings_rate_recurring ?? month.savings_rate,
    }))
    .filter((point): point is { month: string; rate: number } => point.rate !== null)
  if (points.length === 0) return null
  const last = points[points.length - 1]
  return (
    <section className="card cashflow-chart-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">储蓄率趋势</h3>
          <p className="card-sub">
            已排除标记为一次性的收支；负数表示当月支出大于收入。
          </p>
        </div>
      </div>
      <Plot
        data={[
          {
            type: 'scatter',
            mode: 'lines+markers',
            name: '储蓄率',
            x: points.map((point) => point.month),
            y: points.map((point) => point.rate),
            line: { color: SERIES[0], width: 2 },
            marker: { color: SERIES[0], size: 6 },
            hovertemplate: '%{x}<br>储蓄率 %{y:.1%}<extra></extra>',
            cliponaxis: false,
          },
        ]}
        layout={baseLayout({
          xaxis: monthAxis(),
          yaxis: {
            tickformat: '.0%',
            zeroline: true,
            zerolinecolor: AXIS,
            title: { text: '储蓄率', font: { size: 10, color: SECONDARY } },
          },
          annotations: [
            {
              x: last.month,
              y: last.rate,
              text: `${(last.rate * 100).toFixed(1)}%`,
              showarrow: false,
              yshift: 14,
              font: { size: 10, color: SERIES[0] },
            },
          ],
        })}
        config={CONFIG}
        style={{ width: '100%', height: 260 }}
        useResizeHandler
      />
    </section>
  )
}

function structureData(
  categories: CashflowCategoryTotal[],
  limit = 9,
): { labels: string[]; values: number[]; raw: string[] } {
  const top = categories.slice(0, limit)
  const rest = categories.slice(limit)
  if (rest.length > 0) {
    top.push({
      category: '其他类别',
      amount: rest.reduce((sum, item) => sum + item.amount, 0),
      one_off_amount: 0,
      share: rest.reduce((sum, item) => sum + item.share, 0),
      count: rest.reduce((sum, item) => sum + item.count, 0),
    })
  }
  return {
    labels: top.map((item) => item.category).reverse(),
    values: top.map((item) => toWan(item.amount)).reverse(),
    raw: top.map((item) => fmtMoney(item.amount)).reverse(),
  }
}

export function ExpenseStructureChart({ summary }: { summary: CashflowSummary }) {
  if (summary.expense_categories.length === 0) return null
  const data = structureData(summary.expense_categories)
  return (
    <section className="card cashflow-chart-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">支出结构</h3>
          <p className="card-sub">按类别汇总；图中只显示前 9 类。</p>
        </div>
      </div>
      <Plot
        data={[
          {
            type: 'bar',
            orientation: 'h',
            x: data.values,
            y: data.labels,
            customdata: data.raw,
            marker: { color: SERIES[0], line: { color: SURFACE, width: 1 } },
            text: data.values.map((value) => `${value.toFixed(1)}万`),
            textposition: 'outside',
            textfont: { size: 10, color: SECONDARY },
            hovertemplate: '%{y}<br>%{customdata}<extra></extra>',
            cliponaxis: false,
          },
        ]}
        layout={baseLayout({
          margin: { l: 86, r: 54, t: 8, b: 30 },
          xaxis: { ...moneyAxis('万元'), showgrid: true },
          yaxis: { tickfont: { size: 10 }, automargin: true },
        })}
        config={CONFIG}
        style={{ width: '100%', height: Math.max(220, data.labels.length * 28 + 70) }}
        useResizeHandler
      />
    </section>
  )
}

export function InvestmentFlowChart({ summary }: { summary: CashflowSummary }) {
  if (summary.months.length === 0) return null
  const present = BUCKET_ORDER.filter((bucket) =>
    summary.months.some((month) => (month.bucket_buy[bucket] ?? 0) > 0),
  )
  if (present.length === 0) return null
  const x = summary.months.map((month) => month.month)
  const traces: Data[] = present.map((bucket) => ({
    type: 'bar',
    name: BUCKET_LABELS[bucket],
    x,
    y: summary.months.map((month) => toWan(month.bucket_buy[bucket] ?? 0)),
    customdata: summary.months.map((month) =>
      fmtMoney(month.bucket_buy[bucket] ?? 0),
    ),
    marker: {
      color: SERIES[BUCKET_ORDER.indexOf(bucket) % SERIES.length],
    },
    hovertemplate: `%{x}<br>${BUCKET_LABELS[bucket]} %{customdata}<extra></extra>`,
  }))
  return (
    <section className="card cashflow-chart-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">每月投资分配</h3>
          <p className="card-sub">
            按投资桶汇总买入金额；卖出不冲减买入柱，净额见下方表格。
          </p>
        </div>
      </div>
      <Plot
        data={traces}
        layout={baseLayout({
          barmode: 'stack',
          bargap: 0.3,
          xaxis: monthAxis(),
          yaxis: moneyAxis('万元'),
          legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 10 } },
        })}
        config={CONFIG}
        style={{ width: '100%', height: 320 }}
        useResizeHandler
      />
    </section>
  )
}

export function BalanceAllocationChart({
  summary,
}: {
  summary: CashflowSummary
}) {
  if (summary.balances.length === 0) return null
  const present = BUCKET_ORDER.filter((bucket) =>
    summary.balances.some((point) => (point.balances[bucket] ?? 0) > 0),
  )
  const traces: Data[] = present.map((bucket) => ({
    type: 'scatter',
    mode: 'lines',
    name: BUCKET_LABELS[bucket],
    x: summary.balances.map((point) => point.month),
    y: summary.balances.map((point) => toWan(point.balances[bucket] ?? 0)),
    stackgroup: 'assets',
    line: {
      width: 0.5,
      color: SERIES[BUCKET_ORDER.indexOf(bucket) % SERIES.length],
    },
    fillcolor: SERIES[BUCKET_ORDER.indexOf(bucket) % SERIES.length],
    hovertemplate: `%{x}<br>${BUCKET_LABELS[bucket]} %{y:.1f}万<extra></extra>`,
  }))
  return (
    <section className="card cashflow-chart-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">资产配置变化</h3>
          <p className="card-sub">
            来自月度余额快照，今日购买力；只显示有快照的月份。
          </p>
        </div>
      </div>
      <Plot
        data={traces}
        layout={baseLayout({
          xaxis: monthAxis(),
          yaxis: moneyAxis('万元'),
          legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 10 } },
        })}
        config={CONFIG}
        style={{ width: '100%', height: 320 }}
        useResizeHandler
      />
    </section>
  )
}
