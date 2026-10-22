import type { CashflowAssumptionPreview } from '../types'
import { fmtMoney, fmtPct } from '../format'

export default function CashflowAssumptionCard({
  preview,
  onApply,
}: {
  preview: CashflowAssumptionPreview | null
  onApply: () => void
}) {
  const cannotApply = Boolean(
    preview &&
      (preview.monthly_income <= 0 ||
        preview.warnings.some((warning) => warning.includes('只导入'))),
  )
  return (
    <section className="card cashflow-assumption-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">回填完整版假设</h2>
          <p className="card-sub">
            最近 12 个月中位数，已排除“一次性”交易；金额为今日购买力。
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!preview || cannotApply}
          onClick={onApply}
        >
          应用到完整版
        </button>
      </div>
      {preview ? (
        <>
          <div className="cashflow-assumption-grid">
            <div>
              <span>月收入</span>
              <strong>{fmtMoney(preview.monthly_income)}</strong>
            </div>
            <div>
              <span>月支出</span>
              <strong>{fmtMoney(preview.monthly_expense)}</strong>
            </div>
            <div>
              <span>储蓄率</span>
              <strong>
                {preview.savings_rate !== null
                  ? fmtPct(preview.savings_rate)
                  : '—'}
              </strong>
            </div>
            <div>
              <span>使用月份</span>
              <strong>{preview.months_used} 个月</strong>
            </div>
          </div>
          <p className="form-note">
            窗口 {preview.window_start}–{preview.window_end} · 排除一次性{' '}
            {preview.excluded_one_off_count} 笔 · 通胀折算{' '}
            {(preview.inflation_assumption * 100).toFixed(0)}%
          </p>
          {cannotApply ? (
            <p className="form-note danger">
              收入中位数明显低于支出，先补导工资卡/主账户后再回填；当前按钮已禁用。
            </p>
          ) : null}
          {preview.warnings.length > 0 ? (
            <div className="warning-box">
              {preview.warnings.map((warning, index) => (
                <div key={index}>{warning}</div>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <div className="empty-inline">
          至少导入几个月收入/支出后，才能计算回填假设。
        </div>
      )}
    </section>
  )
}
