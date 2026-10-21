import type { EventResult, RunMetrics } from '../types'
import { fmtMoney, fmtPct } from '../format'

function ageLabel(age: number): string {
  return Number.isInteger(age) ? `${age}岁` : `${age.toFixed(1)}岁`
}

function timingSummary(event: EventResult): string {
  const timing = event.timing ?? []
  if (timing.length === 0) return '—'
  const start = event.window_start_age ?? event.age
  const end = event.window_end_age ?? start
  const targets: number[] = []
  for (let age = Math.ceil(start); age <= Math.floor(end); age += 1) {
    targets.push(age)
  }
  if (targets.length === 0) targets.push(start)
  if (!targets.includes(end)) targets.push(end)

  const parts: string[] = []
  for (const age of targets) {
    const point = [...timing].reverse().find((item) => item.age <= age + 1e-9)
    if (point) {
      parts.push(`${ageLabel(age)} ${fmtPct(point.probability)}`)
    }
  }
  return parts.join(' · ')
}

function WindowRow({ event }: { event: EventResult }) {
  const natural = event.natural_success_probability ?? 0
  const deadline = event.deadline_success_probability ?? 0
  const failure = event.failure_probability ?? 0
  const median = event.median_action_age
  const p25 = event.action_age_p25
  const p75 = event.action_age_p75
  const fundingInvestable = event.funding_investable_mean
  const fundingEmergency = event.funding_emergency_mean
  const start = event.window_start_age ?? event.age
  const end = event.window_end_age ?? start
  const action = event.event_type === 'purchase' ? '买入' : '支付'

  return (
    <tr>
      <td>
        <strong>{event.name}</strong>
        <div className="stat-sub">
          {start.toFixed(1)}–{end.toFixed(1)}岁 · 窗口{' '}
          {(event.window_years ?? 0).toFixed(1)} 年
        </div>
      </td>
      <td>
        <strong>总通过 {fmtPct(event.success_probability)}</strong>
        <div className="stat-sub">
          窗口内 {fmtPct(natural)} · 末月 {fmtPct(deadline)} · 未通过{' '}
          {fmtPct(failure)}
        </div>
      </td>
      <td>
        {median !== null && median !== undefined ? (
          <>
            <strong>
              中位{action} {ageLabel(median)}
            </strong>
            <div className="stat-sub">
              25–75% 分位{' '}
              {p25 !== null && p25 !== undefined ? ageLabel(p25) : '—'}–
              {p75 !== null && p75 !== undefined ? ageLabel(p75) : '—'}
            </div>
          </>
        ) : (
          <span className="muted-cell">未完成</span>
        )}
      </td>
      <td>
        {fundingInvestable !== null && fundingInvestable !== undefined ? (
          <>
            <strong>投资资产 {fmtMoney(fundingInvestable)}</strong>
            <div className="stat-sub">
              应急金 {fmtMoney(fundingEmergency ?? 0)}
            </div>
          </>
        ) : (
          <span className="muted-cell">未动用</span>
        )}
      </td>
      <td className="window-timing-cell">{timingSummary(event)}</td>
    </tr>
  )
}

export default function WindowEventsPanel({ metrics }: { metrics: RunMetrics }) {
  const windowEvents = metrics.events.filter(
    (event) => event.has_goal && (event.window_years ?? 0) > 0,
  )
  if (windowEvents.length === 0) return null

  return (
    <section className="card window-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">人生大事窗口：完成时点与通过概率</h2>
          <p className="card-sub">
            窗口内每月检查一次，首次买得起/付得起时执行；末月仍未通过时再试一次
          </p>
        </div>
      </div>

      <div className="table-scroll">
        <table className="mini-table window-table">
          <thead>
            <tr>
              <th>事件 / 窗口</th>
              <th>通过概率</th>
              <th>完成时点</th>
              <th>平均实际动用</th>
              <th>通过概率随时间</th>
            </tr>
          </thead>
          <tbody>
            {windowEvents.map((event, index) => (
              <WindowRow key={`${event.name}-${index}`} event={event} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="chart-footnote">
        资金口径为全部流动资产：投资资产（含现金仓）+ 应急金；非流动资产不会自动卖出。
        “窗口内”指末月之前完成，“末月”指窗口最后一个月完成，“未通过”指窗口内未完成。
        买入资产在末月仍不足时记未通过；一次性支出会赎回全部流动资产并记录缺口。
        完成时点只统计成功路径；平均实际动用只统计有资金动用的路径。
      </p>
    </section>
  )
}
