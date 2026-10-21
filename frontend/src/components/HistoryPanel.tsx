import type { RunListItem } from '../types'
import { fmtMoney, fmtPct } from '../format'

export default function HistoryPanel({
  items,
  activeRunId,
  onLoad,
}: {
  items: RunListItem[]
  activeRunId: string | null
  onLoad: (runId: string) => void
}) {
  return (
    <section className="card history-card">
      <div className="section-head">
        <h3>最近运行</h3>
        <span className="section-note">内容哈希可追溯</span>
      </div>
      {items.length === 0 ? (
        <p className="form-note">还没有运行记录。</p>
      ) : (
        <div className="history-list">
          {items.map((item) => (
            <button
              key={item.run_id}
              type="button"
              className={
                item.run_id === activeRunId
                  ? 'history-item active'
                  : 'history-item'
              }
              onClick={() => onLoad(item.run_id)}
            >
              <span className="history-name">{item.name}</span>
              <span className="history-meta">
                {new Date(item.created_at).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: false,
                })}{' '}
                · {item.run_id}
              </span>
              <span className="history-values">
                期末中位数 {fmtMoney(item.terminal_assets_p50)} · 联合缺口{' '}
                {fmtPct(item.joint_shortfall_probability)}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
