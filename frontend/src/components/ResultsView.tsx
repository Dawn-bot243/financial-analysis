import type { RunResponse } from '../types'
import { fmtMoney, fmtPct } from '../format'
import StatTile from './StatTile'
import FanChart from './FanChart'
import DrawdownChart from './DrawdownChart'
import ShortfallPanel from './ShortfallPanel'
import WindowEventsPanel from './WindowEventsPanel'
import ExplanationPanel from './ExplanationPanel'
import RunMeta from './RunMeta'

const kindLabels: Record<string, string> = {
  investable: '投资资产',
  emergency: '应急金',
  illiquid: '非流动资产',
  liability: '负债',
}

function CompositionPanel({ run }: { run: RunResponse }) {
  const metrics = run.metrics
  const assets = metrics.terminal_composition.filter(
    (item) => item.kind !== 'liability',
  )
  const liabilities = metrics.terminal_composition.filter(
    (item) => item.kind === 'liability',
  )
  return (
    <section className="card composition-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">期末资产构成</h2>
          <p className="card-sub">
            各项期末值的中位数 · 未扣负债的资产与负债分开列示
          </p>
        </div>
        <span className="run-ref">run {run.run_id}</span>
      </div>
      <div className="table-scroll">
        <table className="mini-table composition-table">
          <thead>
            <tr>
              <th>项目</th>
              <th>类别</th>
              <th>期末中位数</th>
            </tr>
          </thead>
          <tbody>
            {assets.map((item, index) => (
              <tr key={`${item.label}-${index}`}>
                <td>{item.label}</td>
                <td>
                  <span className="role-tag">
                    {kindLabels[item.kind] ?? item.kind}
                  </span>
                </td>
                <td>{fmtMoney(item.value)}</td>
              </tr>
            ))}
            {liabilities.map((item, index) => (
              <tr className="liability-row" key={`liability-${index}`}>
                <td>{item.label}</td>
                <td>
                  <span className="role-tag">负债</span>
                </td>
                <td>-{fmtMoney(item.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="chart-footnote">
        中位数构成之和不等于总额中位数；非流动资产按固定增长率估值，未建模价格波动。
        应急金目标为 {metrics.emergency_fund_target_months.toFixed(0)} 个月开销。
      </p>
    </section>
  )
}

export default function ResultsView({ run }: { run: RunResponse }) {
  const metrics = run.metrics
  const jointSuccess = 1 - metrics.joint_shortfall_probability
  const jointSuccessLow = 1 - metrics.joint_shortfall_ci95_high
  const jointSuccessHigh = 1 - metrics.joint_shortfall_ci95_low
  const terminalEmergency = metrics.terminal_emergency_fund?.p50 ?? 0

  return (
    <div className="results">
      {run.warnings.length > 0 ? (
        <div className="warning-box">
          {run.warnings.map((warning, index) => (
            <div key={index}>{warning}</div>
          ))}
        </div>
      ) : null}

      <div className="metric-grid">
        <StatTile
          hero
          label="期末流动资产中位数"
          value={fmtMoney(metrics.terminal_assets.p50)}
          sub={`${run.request.horizon_years} 年末 · 5–95 分位 ${fmtMoney(
            metrics.terminal_assets.p5,
          )}–${fmtMoney(metrics.terminal_assets.p95)}`}
        />
        <StatTile
          label="期末净资产中位数"
          value={fmtMoney(metrics.terminal_net_worth.p50)}
          sub="流动资产 + 非流动资产 - 负债"
        />
        <StatTile
          label="期末应急金中位数"
          value={fmtMoney(terminalEmergency)}
          sub={`目标 ${metrics.emergency_fund_target_months.toFixed(0)} 个月开销`}
        />
        <StatTile
          label="最大回撤中位数"
          value={fmtPct(metrics.max_drawdown.p50)}
          sub={`时间加权 · 95 分位 ${fmtPct(metrics.max_drawdown.p95)}`}
        />
        <StatTile
          label="目标事件通过率"
          value={fmtPct(jointSuccess)}
          sub={`所有目标事件同时通过 · 95% CI ${fmtPct(
            jointSuccessLow,
          )}–${fmtPct(jointSuccessHigh)}`}
        />
        <StatTile
          label="曾耗尽金融资产"
          value={fmtPct(metrics.ruin_probability)}
          sub={`95% CI ${fmtPct(metrics.ruin_ci95_low)}–${fmtPct(
            metrics.ruin_ci95_high,
          )}`}
        />
      </div>

      <FanChart run={run} />

      <div className="two-col">
        <DrawdownChart run={run} />
        <ShortfallPanel metrics={metrics} />
      </div>

      <WindowEventsPanel metrics={metrics} />

      <CompositionPanel run={run} />
      <ExplanationPanel explanation={run.explanation} />
      <RunMeta run={run} />
    </div>
  )
}
