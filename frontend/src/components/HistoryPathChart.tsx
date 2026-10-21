import Plot from 'react-plotly.js'
import type { Config, Data, Layout } from 'plotly.js'
import type { HistoryResponse } from '../types'
import { fmtMoney, toWan } from '../format'

const VALUE = '#1c5cab'
const INVESTED = '#898781'
const GRID = '#e1e0d9'
const AXIS = '#c3c2b7'
const SECONDARY = '#52514e'

export default function HistoryPathChart({
  history,
}: {
  history: HistoryResponse
}) {
  const points = history.path
  const x = points.map((point) => point.date)
  const value = points.map((point) => toWan(point.value))
  const invested = points.map((point) => toWan(point.invested))

  const traces: Data[] = [
    {
      x,
      y: invested,
      type: 'scatter',
      mode: 'lines',
      line: { color: INVESTED, width: 2, dash: 'dot' },
      name: '累计投入',
      hovertemplate: '<b>%{y:.1f}万元</b> · 累计投入<extra></extra>',
    },
    {
      x,
      y: value,
      type: 'scatter',
      mode: 'lines',
      line: { color: VALUE, width: 2 },
      name: '定投市值',
      hovertemplate: '<b>%{y:.1f}万元</b> · 定投市值<extra></extra>',
    },
  ]

  const layout: Partial<Layout> = {
    margin: { l: 58, r: 26, t: 36, b: 52 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family:
        'system-ui, -apple-system, "Segoe UI", "Noto Sans SC", sans-serif',
      size: 12,
      color: SECONDARY,
    },
    xaxis: {
      type: 'date',
      title: { text: '日期' },
      gridcolor: GRID,
      zeroline: false,
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
      y: -0.22,
      font: { size: 11 },
      bgcolor: 'rgba(0,0,0,0)',
    },
    shapes: [
      {
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        y0: 0,
        y1: 0,
        line: { color: AXIS, width: 1 },
      },
    ],
    showlegend: true,
  }

  const config: Partial<Config> = {
    displayModeBar: false,
    responsive: true,
  }

  return (
    <section className="card chart-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">定投市值与累计投入</h2>
          <p className="card-sub">
            实际历史路径 · 今日购买力（已按 2% 通胀折算） · 每月第一个交易日投入 ·
            期末 {fmtMoney(history.terminal_value)}
          </p>
        </div>
        <span className="run-ref">history {history.run_id}</span>
      </div>
      <Plot
        data={traces}
        layout={layout}
        config={config}
        style={{ width: '100%', height: 380 }}
        useResizeHandler
      />
      <p className="chart-footnote">
        累计投入 = 初始资金 + 已投入月数 × 每月金额；定投市值是实际历史路径。
        所有金额均为今日购买力，已按 2% 通胀折算。最大回撤按时间加权单位净值计算，
        剔除投入的影响；未计交易费用和税费。
      </p>
      <details className="table-view">
        <summary>数据表（每年末）</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>定投市值（万元）</th>
                <th>累计投入（万元）</th>
                <th>收益（万元）</th>
              </tr>
            </thead>
            <tbody>
              {history.yearly.map((point) => (
                <tr key={point.date}>
                  <td>{point.date}</td>
                  <td>{toWan(point.value).toFixed(1)}</td>
                  <td>{toWan(point.invested).toFixed(1)}</td>
                  <td>{toWan(point.value - point.invested).toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}
