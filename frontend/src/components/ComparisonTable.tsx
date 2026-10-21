import Plot from 'react-plotly.js'
import type { Config, Data, Layout } from 'plotly.js'
import type { CompareItem, CompareResponse } from '../types'
import { fmtMoney, fmtPct, toWan } from '../format'

function PathChart({ items }: { items: CompareItem[] }) {
  const baseline = items[0]?.terminal_assets_p50 ?? 0
  const x = items.map((item) => toWan(item.terminal_assets_p50))
  const p25 = items.map((item) =>
    toWan(item.terminal_assets_p25 ?? item.terminal_assets_p50),
  )
  const p75 = items.map((item) =>
    toWan(item.terminal_assets_p75 ?? item.terminal_assets_p50),
  )
  const delta = items.map((item) => toWan(item.terminal_assets_p50 - baseline))
  const text = items.map((item, index) =>
    index === 0
      ? `${toWan(item.terminal_assets_p50).toFixed(1)}万`
      : `${toWan(item.terminal_assets_p50).toFixed(1)}万 (${delta[index] >= 0 ? '+' : ''}${delta[index].toFixed(1)})`,
  )
  const customdata = items.map((_, index) => [
    p25[index],
    p75[index],
    delta[index],
  ])
  const maxX = Math.max(...x, 1)

  const trace: Data = {
    x,
    y: items.map((item) => item.name),
    type: 'scatter',
    mode: 'markers',
    marker: {
      size: 11,
      color: items.map((_, index) => (index === 0 ? '#1c5cab' : '#2a78d6')),
      line: { color: '#fcfcfb', width: 2 },
    },
    error_x: {
      type: 'data',
      symmetric: false,
      array: p75.map((value, index) => Math.max(0, value - x[index])),
      arrayminus: x.map((value, index) => Math.max(0, value - p25[index])),
      color: '#898781',
      thickness: 1.5,
      width: 4,
    },
    text,
    textposition: 'middle right',
    textfont: { size: 11, color: '#0b0b0b' },
    cliponaxis: false,
    customdata,
    hovertemplate:
      '<b>%{y}</b><br>中位数 %{x:.1f}万元<br>' +
      '25–75分位 %{customdata[0]:.1f}–%{customdata[1]:.1f}万元<br>' +
      '相对基准 %{customdata[2]:+.1f}万元<extra></extra>',
  }

  const layout: Partial<Layout> = {
    margin: { l: 132, r: 96, t: 16, b: 44 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family:
        'system-ui, -apple-system, "Segoe UI", "Noto Sans SC", sans-serif',
      size: 11,
      color: '#52514e',
    },
    xaxis: {
      title: { text: '期末流动资产（万元）' },
      gridcolor: '#e1e0d9',
      zeroline: false,
      rangemode: 'tozero',
      range: [0, maxX * 1.3],
    },
    yaxis: {
      automargin: true,
      autorange: 'reversed',
      gridcolor: '#e1e0d9',
      zeroline: false,
    },
    hoverlabel: {
      bgcolor: '#fcfcfb',
      bordercolor: '#e1e0d9',
      font: { color: '#0b0b0b' },
    },
    showlegend: false,
  }

  const config: Partial<Config> = {
    displayModeBar: false,
    responsive: true,
  }

  return (
    <Plot
      data={[trace]}
      layout={layout}
      config={config}
      style={{ width: '100%', height: Math.max(210, 52 * items.length + 90) }}
      useResizeHandler
    />
  )
}

export default function ComparisonTable({
  comparison,
  mode = 'window',
}: {
  comparison: CompareResponse
  mode?: 'window' | 'path'
}) {
  const items = comparison.items
  if (items.length === 0) {
    return (
      <div className="empty-card">
        <h2>对比结果为空</h2>
        <p>请先在左侧选择情景并运行对比。</p>
      </div>
    )
  }
  const isPath = mode === 'path'
  const max = Math.max(...items.map((item) => item.terminal_assets_p50), 1)
  const baseline = items[0].terminal_assets_p50

  return (
    <section className="card comparison-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">
            {isPath ? '人生道路对比' : '历史校准窗口对比'}
          </h2>
          <p className="card-sub">
            {isPath
              ? '以当前路径为基准；相同 seed、路径数、资产假设和持仓，只改变包含的人生事件'
              : '近 5 / 10 / 15 年 · 相同随机种子、路径数、家庭假设和资产顺序'}
          </p>
        </div>
      </div>

      {isPath ? <PathChart items={items} /> : null}

      <div className="table-scroll">
        <table className="comparison-table">
          <thead>
            <tr>
              <th>{isPath ? '路径' : '校准窗口'}</th>
              <th>期末流动资产中位数</th>
              {isPath ? <th>相对基准</th> : null}
              <th>期末净资产中位数</th>
              <th>应急金中位数</th>
              <th>最大回撤中位数</th>
              <th>目标事件缺口</th>
              <th>曾耗尽</th>
              <th>累计投入</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const p25 = item.terminal_assets_p25
              const p75 = item.terminal_assets_p75
              const delta = item.terminal_assets_p50 - baseline
              return (
                <tr key={item.run_id}>
                  <td>
                    <strong>{item.name}</strong>
                    {isPath && index === 0 ? (
                      <span className="role-tag baseline-tag">基准</span>
                    ) : null}
                    <div className="run-ref">run {item.run_id}</div>
                  </td>
                  <td>
                    <div>{fmtMoney(item.terminal_assets_p50)}</div>
                    <div className="range-note">
                      {p25 !== null &&
                      p25 !== undefined &&
                      p75 !== null &&
                      p75 !== undefined
                        ? `25–75 分位 ${fmtMoney(p25)}–${fmtMoney(p75)}`
                        : '—'}
                    </div>
                    <div className="data-bar">
                      <div
                        className="data-bar-fill"
                        style={{
                          width: `${(item.terminal_assets_p50 / max) * 100}%`,
                        }}
                      />
                    </div>
                  </td>
                  {isPath ? (
                    <td
                      className={
                        delta >= 0 ? 'delta-positive' : 'delta-negative'
                      }
                    >
                      {delta >= 0 ? '+' : ''}
                      {fmtMoney(delta)}
                    </td>
                  ) : null}
                  <td>{fmtMoney(item.terminal_net_worth_p50)}</td>
                  <td>
                    {item.terminal_emergency_p50 !== null &&
                    item.terminal_emergency_p50 !== undefined
                      ? fmtMoney(item.terminal_emergency_p50)
                      : '—'}
                  </td>
                  <td>{fmtPct(item.max_drawdown_p50)}</td>
                  <td>{fmtPct(item.joint_shortfall_probability)}</td>
                  <td>{fmtPct(item.ruin_probability)}</td>
                  <td>
                    {item.total_contributions !== null &&
                    item.total_contributions !== undefined
                      ? fmtMoney(item.total_contributions)
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="chart-footnote">
        {isPath
          ? '所有路径共用同一随机种子和路径数（共同随机数），差异来自包含的事件，不是模拟噪声。买入失败不强制赎回；这是条件对比，不是因果推断。'
          : '三组情景使用同一随机种子和路径数（共同随机数），差异来自历史校准窗口，而不是模拟噪声。“目标事件缺口”是至少一个目标事件未通过的概率；“曾耗尽”是路径中金融资产曾归零的占比。历史窗口的实现值不是未来预期；窗口差异本身就是一种敏感性检验。'}
      </p>
    </section>
  )
}
