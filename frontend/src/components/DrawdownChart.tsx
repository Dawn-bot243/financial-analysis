import Plot from 'react-plotly.js'
import type { Annotations, Config, Data, Layout, Shape } from 'plotly.js'
import type { RunResponse } from '../types'
import { fmtPct } from '../format'

const BAR = '#86b6ef'
const GRID = '#e1e0d9'
const SECONDARY = '#52514e'
const MEDIAN = '#1c5cab'
const CRITICAL = '#d03b3b'

export default function DrawdownChart({ run }: { run: RunResponse }) {
  const summary = run.metrics.max_drawdown
  const total = summary.hist_counts.reduce((sum, count) => sum + count, 0) || 1
  const counts = summary.hist_counts
  const edges = summary.hist_edges
  const x = edges.slice(0, -1).map((edge, index) => ((edge + edges[index + 1]) / 2) * 100)
  const y = counts.map((count) => (count / total) * 100)
  const ranges = edges.slice(0, -1).map((edge, index) => [
    edge * 100,
    edges[index + 1] * 100,
  ])

  const data: Data[] = [
    {
      x,
      y,
      type: 'bar',
      marker: { color: BAR, line: { width: 0 } },
      customdata: ranges,
      hovertemplate:
        '最大回撤 %{customdata[0]:.0f}%–%{customdata[1]:.0f}%<br><b>%{y:.1f}%</b> 的路径<extra></extra>',
    },
  ]

  const shapes: Partial<Shape>[] = [
    {
      type: 'line',
      x0: summary.p50 * 100,
      x1: summary.p50 * 100,
      y0: 0,
      y1: 1,
      yref: 'paper',
      line: { color: MEDIAN, width: 1.5 },
    },
    {
      type: 'line',
      x0: summary.p95 * 100,
      x1: summary.p95 * 100,
      y0: 0,
      y1: 1,
      yref: 'paper',
      line: { color: CRITICAL, width: 1.5 },
    },
  ]

  const annotations: Partial<Annotations>[] = [
    {
      x: summary.p50 * 100,
      y: 1.02,
      yref: 'paper',
      text: '中位数',
      showarrow: false,
      font: { size: 10, color: SECONDARY },
      xanchor: 'right',
    },
    {
      x: summary.p95 * 100,
      y: 1.02,
      yref: 'paper',
      text: '95分位',
      showarrow: false,
      font: { size: 10, color: CRITICAL },
      xanchor: 'left',
    },
  ]

  const layout: Partial<Layout> = {
    margin: { l: 58, r: 18, t: 32, b: 46 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family:
        'system-ui, -apple-system, "Segoe UI", "Noto Sans SC", sans-serif',
      size: 11,
      color: SECONDARY,
    },
    xaxis: {
      title: { text: '时间加权最大回撤（%）' },
      range: [0, 100],
      gridcolor: GRID,
      zeroline: false,
    },
    yaxis: {
      title: { text: '路径占比（%）' },
      rangemode: 'tozero',
      gridcolor: GRID,
      zeroline: false,
    },
    bargap: 0.32,
    hoverlabel: {
      bgcolor: '#fcfcfb',
      bordercolor: GRID,
      font: { color: '#0b0b0b' },
    },
    shapes,
    annotations,
  }

  const config: Partial<Config> = {
    displayModeBar: false,
    responsive: true,
  }

  return (
    <section className="card chart-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">最大回撤分布</h2>
          <p className="card-sub">
            每条路径先取回撤最大值 · 时间加权 · 中位数 {fmtPct(summary.p50)} · 95分位{' '}
            {fmtPct(summary.p95)}
          </p>
        </div>
        <span className="run-ref">run {run.run_id}</span>
      </div>
      <Plot
        data={data}
        layout={layout}
        config={config}
        style={{ width: '100%', height: 300 }}
        useResizeHandler
      />
      <p className="chart-footnote">
        回撤按组合的时间加权净值计算，已剔除投入和赎回现金流的影响；月末估值不会捕捉月内回撤。
      </p>
      <details className="table-view">
        <summary>数据表（分箱）</summary>
        <table>
          <thead>
            <tr>
              <th>回撤区间</th>
              <th>路径数</th>
              <th>占比</th>
            </tr>
          </thead>
          <tbody>
            {counts.map((count, index) => (
              <tr key={index}>
                <td>
                  {(edges[index] * 100).toFixed(0)}%–{(edges[index + 1] * 100).toFixed(0)}%
                </td>
                <td>{count}</td>
                <td>{((count / total) * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}
