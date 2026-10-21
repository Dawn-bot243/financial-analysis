import Plot from 'react-plotly.js'
import type { Annotations, Config, Data, Layout, Shape } from 'plotly.js'
import type { RunResponse } from '../types'
import { fmtMoney, toWan } from '../format'

const BAND_OUTER = 'rgba(134, 182, 239, 0.22)'
const BAND_INNER = 'rgba(57, 135, 229, 0.16)'
const MEDIAN = '#1c5cab'
const NET_WORTH = '#898781'
const EVENT = '#b45309'
const SALE = '#898781'
const GRID = '#e1e0d9'
const AXIS = '#c3c2b7'
const SECONDARY = '#52514e'

export default function FanChart({
  run,
  simple = false,
}: {
  run: RunResponse
  simple?: boolean
}) {
  const metrics = run.metrics
  const horizonMonths = run.request.horizon_years * 12
  const currentAge = run.request.household.current_age
  const initialWan = toWan(metrics.initial_capital)
  const initialNetWorth = toWan(
    metrics.initial_net_worth ??
      metrics.initial_capital -
        run.request.household.liabilities.reduce(
          (sum, liability) => sum + liability.balance,
          0,
        ),
  )
  const initialEmergency = toWan(metrics.initial_emergency_fund ?? 0)
  const x = [0, ...metrics.years]
  const p5 = [initialWan, ...metrics.assets.p5.map(toWan)]
  const p25 = [initialWan, ...metrics.assets.p25.map(toWan)]
  const p50 = [initialWan, ...metrics.assets.p50.map(toWan)]
  const p75 = [initialWan, ...metrics.assets.p75.map(toWan)]
  const p95 = [initialWan, ...metrics.assets.p95.map(toWan)]
  const netWorth50 = [initialNetWorth, ...metrics.net_worth.p50.map(toWan)]
  const emergency50 = [
    initialEmergency,
    ...(metrics.emergency_fund?.p50 ?? []).map(toWan),
  ]

  const traces: Data[] = [
    {
      x,
      y: p5,
      type: 'scatter',
      mode: 'lines',
      line: { width: 0 },
      showlegend: false,
      hovertemplate: '<b>%{y:.1f}万元</b> · 5分位<extra></extra>',
    },
    {
      x,
      y: p25,
      type: 'scatter',
      mode: 'lines',
      line: { width: 0 },
      fill: 'tonexty',
      fillcolor: BAND_OUTER,
      name: '5–25分位',
      legendrank: 1,
      hovertemplate: '<b>%{y:.1f}万元</b> · 25分位<extra></extra>',
    },
    {
      x,
      y: p75,
      type: 'scatter',
      mode: 'lines',
      line: { width: 0 },
      fill: 'tonexty',
      fillcolor: BAND_INNER,
      name: '25–75分位',
      legendrank: 2,
      hovertemplate: '<b>%{y:.1f}万元</b> · 75分位<extra></extra>',
    },
    {
      x,
      y: p95,
      type: 'scatter',
      mode: 'lines',
      line: { width: 0 },
      fill: 'tonexty',
      fillcolor: BAND_OUTER,
      name: '75–95分位',
      legendrank: 3,
      hovertemplate: '<b>%{y:.1f}万元</b> · 95分位<extra></extra>',
    },
    {
      x,
      y: p50,
      type: 'scatter',
      mode: 'lines',
      line: { color: MEDIAN, width: 2 },
      name: '中位数',
      legendrank: 4,
      hovertemplate: '<b>%{y:.1f}万元</b> · 中位数<extra></extra>',
    },
  ]
  if (!simple) {
    traces.push({
      x,
      y: netWorth50,
      type: 'scatter',
      mode: 'lines',
      line: { color: NET_WORTH, width: 2 },
      name: '净资产中位数',
      legendrank: 5,
      hovertemplate: '<b>%{y:.1f}万元</b> · 净资产中位数<extra></extra>',
    })
  }

  const eventShapes: Partial<Shape>[] = simple
    ? []
    : metrics.events.map((event) => ({
        type: 'line',
        x0: event.month / 12,
        x1: event.month / 12,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: EVENT, width: 1, dash: 'dot' },
      }))
  const eventAnnotations: Partial<Annotations>[] = simple
    ? []
    : metrics.events.map((event) => ({
        x: event.month / 12,
        y: 1.02,
        yref: 'paper',
        text: event.name,
        showarrow: false,
        font: { size: 10, color: EVENT },
        xanchor: 'center',
      }))

  const saleMarkers: { name: string; month: number }[] = []
  if (!simple) {
    for (const event of run.request.household.events) {
      const sellAge = event.purchase?.sell_age
      if (sellAge === null || sellAge === undefined) continue
      const month = Math.round((sellAge - currentAge) * 12)
      if (month >= 1 && month <= horizonMonths) {
        saleMarkers.push({ name: `卖出${event.name}`, month })
      }
    }
    for (const holding of run.request.household.holdings) {
      if (holding.liquidity !== 'illiquid' || holding.sell_age === null) continue
      const month = Math.round((holding.sell_age - currentAge) * 12)
      if (month >= 1 && month <= horizonMonths) {
        saleMarkers.push({ name: `卖出${holding.label}`, month })
      }
    }
  }
  const saleShapes: Partial<Shape>[] = saleMarkers.map((marker) => ({
    type: 'line',
    x0: marker.month / 12,
    x1: marker.month / 12,
    y0: 0,
    y1: 1,
    yref: 'paper',
    line: { color: SALE, width: 1, dash: 'dot' },
  }))
  const saleAnnotations: Partial<Annotations>[] = saleMarkers.map((marker) => ({
    x: marker.month / 12,
    y: 1.02,
    yref: 'paper',
    text: marker.name,
    showarrow: false,
    font: { size: 10, color: SALE },
    xanchor: 'center',
  }))

  const layout: Partial<Layout> = {
    margin: { l: 58, r: 26, t: 40, b: 52 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family:
        'system-ui, -apple-system, "Segoe UI", "Noto Sans SC", sans-serif',
      size: 12,
      color: SECONDARY,
    },
    xaxis: {
      title: { text: '年' },
      gridcolor: GRID,
      zeroline: false,
      tickmode: 'linear',
      dtick: 1,
      range: [0, run.request.horizon_years],
    },
    yaxis: {
      title: { text: '万元（今日购买力）' },
      gridcolor: GRID,
      zeroline: false,
      separatethousands: true,
    },
    hovermode: 'x unified',
    hoverlabel: {
      bgcolor: '#fcfcfb',
      bordercolor: GRID,
      font: { color: '#0b0b0b' },
    },
    legend: {
      orientation: 'h',
      x: 0,
      y: -0.24,
      font: { size: 11 },
      bgcolor: 'rgba(0,0,0,0)',
      traceorder: 'normal',
    },
    shapes: [
      {
        type: 'line',
        x0: 0,
        x1: run.request.horizon_years,
        y0: 0,
        y1: 0,
        line: { color: AXIS, width: 1 },
      },
      ...eventShapes,
      ...saleShapes,
    ],
    annotations: [
      ...eventAnnotations,
      ...saleAnnotations,
      {
        x: run.request.horizon_years - 0.2,
        y: p50[p50.length - 1],
        text: '中位数',
        showarrow: false,
        xanchor: 'right',
        yshift: 12,
        font: { size: 11, color: MEDIAN },
      },
    ],
    showlegend: true,
  }

  const config: Partial<Config> = {
    displayModeBar: false,
    responsive: true,
  }

  const annualIndices = metrics.years
    .map((_, index) => index)
    .filter((index) => (index + 1) % 12 === 0)

  return (
    <section className="card chart-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">流动资产路径分位</h2>
          <p className="card-sub">
            {run.request.name} · 5/25/50/75/95 分位 · 今日购买力
            {simple ? ' · 每月按目标比例投入' : ' · 含应急金 · 灰线为净资产中位数'}
          </p>
        </div>
        <span className="run-ref">run {run.run_id}</span>
      </div>
      <Plot
        data={traces}
        layout={layout}
        config={config}
        style={{ width: '100%', height: 438 }}
        useResizeHandler
      />
      <p className="chart-footnote">
        {simple
          ? '分位数为逐时点边际分布，不代表单条路径始终落在带内；每月投入按目标权重建仓，年度再平衡，未计交易成本。'
          : '分位数为逐时点边际分布，不代表单条路径始终落在带内。橙线为买入/一次性事件，灰线为卖出事件；买入失败不强制赎回，一次性支出不足会强制赎回。'}
        中位数期末 {fmtMoney(metrics.terminal_assets.p50)}，5%–95% 分位区间{' '}
        {fmtMoney(metrics.terminal_assets.p5)}–{fmtMoney(metrics.terminal_assets.p95)}。
      </p>
      <details className="table-view">
        <summary>数据表（每年末）</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>年</th>
                <th>5分位</th>
                <th>25分位</th>
                <th>中位数</th>
                <th>75分位</th>
                <th>95分位</th>
                {!simple ? (
                  <>
                    <th>应急金中位</th>
                    <th>净资产中位数</th>
                  </>
                ) : null}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>起点</td>
                <td>{initialWan.toFixed(1)}</td>
                <td>{initialWan.toFixed(1)}</td>
                <td>{initialWan.toFixed(1)}</td>
                <td>{initialWan.toFixed(1)}</td>
                <td>{initialWan.toFixed(1)}</td>
                {!simple ? (
                  <>
                    <td>{initialEmergency.toFixed(1)}</td>
                    <td>{initialNetWorth.toFixed(1)}</td>
                  </>
                ) : null}
              </tr>
              {annualIndices.map((index) => (
                <tr key={index}>
                  <td>{metrics.years[index].toFixed(0)}</td>
                  <td>{toWan(metrics.assets.p5[index]).toFixed(1)}</td>
                  <td>{toWan(metrics.assets.p25[index]).toFixed(1)}</td>
                  <td>{toWan(metrics.assets.p50[index]).toFixed(1)}</td>
                  <td>{toWan(metrics.assets.p75[index]).toFixed(1)}</td>
                  <td>{toWan(metrics.assets.p95[index]).toFixed(1)}</td>
                  {!simple ? (
                    <>
                      <td>
                        {emergency50[index + 1] !== undefined
                          ? emergency50[index + 1].toFixed(1)
                          : '—'}
                      </td>
                      <td>{toWan(metrics.net_worth.p50[index]).toFixed(1)}</td>
                    </>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}
