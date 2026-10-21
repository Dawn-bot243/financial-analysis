import type { EventResult, RunMetrics } from '../types'
import { fmtMoney, fmtPct } from '../format'

function severity(probability: number): string {
  if (probability >= 0.8) return 'good'
  if (probability >= 0.5) return 'serious'
  return 'critical'
}

const typeLabels: Record<string, string> = {
  purchase: '买入资产',
  cashflow: '一次性目标',
  recurring: '持续现金流',
}

function EventRow({ event }: { event: EventResult }) {
  if (!event.has_goal) {
    return (
      <div className="shortfall-row">
        <div className="shortfall-head">
          <strong>{event.name}</strong>
          <span>
            {event.age.toFixed(0)}岁 · {typeLabels.recurring}
          </span>
        </div>
        <p className="form-note">
          持续收入/支出已并入月度现金流，不参与一次性目标通过率。
        </p>
      </div>
    )
  }
  const hasWindow = (event.window_years ?? 0) > 0
  const timing =
    hasWindow &&
    event.window_start_age !== null &&
    event.window_start_age !== undefined &&
    event.window_end_age !== null &&
    event.window_end_age !== undefined
      ? `${event.window_start_age.toFixed(1)}–${event.window_end_age.toFixed(
          1,
        )}岁 · 窗口 ${(event.window_years ?? 0).toFixed(1)} 年`
      : `${event.age.toFixed(0)}岁`
  return (
    <div className="shortfall-row">
      <div className="shortfall-head">
        <strong>{event.name}</strong>
        <span>
          {timing} · {typeLabels[event.event_type] ?? '目标'} · 首付/目标{' '}
          {fmtMoney(event.amount)}
          {event.median_cost !== null && event.median_cost !== undefined
            ? ` · 实际中位 ${fmtMoney(event.median_cost)}`
            : ''}
        </span>
      </div>
      <div className="meter">
        <div
          className={`meter-fill ${severity(event.success_probability)}`}
          style={{ width: `${event.success_probability * 100}%` }}
        />
      </div>
      <div className="shortfall-meta">
        <span>通过率 {fmtPct(event.success_probability)}</span>
        <span>
          95% CI {fmtPct(event.success_ci95_low)}–{fmtPct(event.success_ci95_high)}
        </span>
        <span>失败平均缺口 {fmtMoney(event.mean_gap)}</span>
        <span>失败缺口中位 {fmtMoney(event.p50_gap)}</span>
      </div>
      {hasWindow ? (
        <div className="shortfall-meta">
          <span>
            窗口内{' '}
            {fmtPct(event.natural_success_probability ?? 0)}
          </span>
          <span>
            末月 {fmtPct(event.deadline_success_probability ?? 0)}
          </span>
          <span>未通过 {fmtPct(event.failure_probability ?? 0)}</span>
          <span>
            中位完成{' '}
            {event.median_action_age !== null &&
            event.median_action_age !== undefined
              ? `${event.median_action_age.toFixed(1)}岁`
              : '未完成'}
          </span>
        </div>
      ) : null}
    </div>
  )
}

export default function ShortfallPanel({ metrics }: { metrics: RunMetrics }) {
  const jointSuccess = 1 - metrics.joint_shortfall_probability
  const jointSuccessLow = 1 - metrics.joint_shortfall_ci95_high
  const jointSuccessHigh = 1 - metrics.joint_shortfall_ci95_low

  return (
    <section className="card shortfall-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">目标事件与资金缺口</h2>
          <p className="card-sub">
            通过率是“不调整行为”时的条件概率；持续收支不计入联合通过率
          </p>
        </div>
      </div>

      <div className="shortfall-summary">
        <div className="shortfall-stat">
          <span className="stat-label">目标事件联合通过率</span>
          <strong>{fmtPct(jointSuccess)}</strong>
          <span className="stat-sub">
            95% CI {fmtPct(jointSuccessLow)}–{fmtPct(jointSuccessHigh)}
          </span>
        </div>
        <div className="shortfall-stat">
          <span className="stat-label">至少一个目标未通过</span>
          <strong>{fmtPct(metrics.joint_shortfall_probability)}</strong>
          <span className="stat-sub">
            95% CI {fmtPct(metrics.joint_shortfall_ci95_low)}–
            {fmtPct(metrics.joint_shortfall_ci95_high)}
          </span>
        </div>
        <div className="shortfall-stat">
          <span className="stat-label">曾耗尽金融资产</span>
          <strong>{fmtPct(metrics.ruin_probability)}</strong>
          <span className="stat-sub">
            95% CI {fmtPct(metrics.ruin_ci95_low)}–{fmtPct(metrics.ruin_ci95_high)}
          </span>
        </div>
      </div>

      {metrics.events.length === 0 ? (
        <p className="form-note">本次没有落在推演区间内的人生事件。</p>
      ) : (
        metrics.events.map((event, index) => (
          <EventRow key={`${event.name}-${index}`} event={event} />
        ))
      )}

      <p className="chart-footnote">
        时间窗内每月用全部流动资产（投资资产 + 现金 + 应急金）检查一次。
        窗口末月会用全部流动资产再试一次：买入资产仍不足则记未通过，不会自动卖房；
        一次性支出会赎回全部流动资产并记录缺口。通过率会低于“只看总资产是否达标”的直觉。
      </p>
    </section>
  )
}
