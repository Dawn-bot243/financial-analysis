import { useEffect, useState } from 'react'
import type {
  CashflowDirection,
  CashflowTransaction,
  CashflowTransactionPatch,
  InvestmentBucket,
} from '../types'
import { updateCashflowTransaction } from '../api'
import { fmtYuan } from '../format'

const DIRECTIONS: { value: CashflowDirection; label: string }[] = [
  { value: 'income', label: '收入' },
  { value: 'expense', label: '支出' },
  { value: 'investment', label: '投资' },
  { value: 'transfer', label: '转账' },
  { value: 'ignore', label: '不计' },
]

const SOURCE_LABELS: Record<string, string> = {
  alipay: '支付宝',
  wechat: '微信',
  bank: '银行',
  generic: '通用',
}

const BUCKETS: { value: InvestmentBucket; label: string }[] = [
  { value: 'cash', label: '现金/货币' },
  { value: 'a_share', label: 'A股基金' },
  { value: 'overseas', label: '海外基金' },
  { value: 'gold', label: '黄金' },
  { value: 'bond', label: '债券' },
  { value: 'other', label: '其他' },
]

function TransactionRow({
  transaction,
  onChanged,
}: {
  transaction: CashflowTransaction
  onChanged: () => void
}) {
  const [category, setCategory] = useState(transaction.category)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setCategory(transaction.category)
  }, [transaction.category])

  const patch = async (payload: CashflowTransactionPatch) => {
    setSaving(true)
    try {
      await updateCashflowTransaction(transaction.id, payload)
      onChanged()
    } finally {
      setSaving(false)
    }
  }

  return (
    <tr className={transaction.is_one_off ? 'cashflow-one-off-row' : undefined}>
      <td className="nowrap">{transaction.date}</td>
      <td className="nowrap">{fmtYuan(transaction.amount)}</td>
      <td>
        <strong>{transaction.counterparty || '—'}</strong>
        <div className="cashflow-desc">{transaction.description || '—'}</div>
      </td>
      <td>
        <select
          value={transaction.direction}
          disabled={saving}
          onChange={(event) =>
            patch({
              direction: event.target.value as CashflowDirection,
            })
          }
        >
          {DIRECTIONS.map((item) => (
            <option value={item.value} key={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          value={category}
          disabled={saving}
          onChange={(event) => setCategory(event.target.value)}
          onBlur={() => {
            if (category.trim() && category !== transaction.category) {
              patch({ category: category.trim() })
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur()
          }}
        />
      </td>
      <td>
        {transaction.direction === 'investment' ? (
          <select
            value={transaction.bucket ?? 'other'}
            disabled={saving}
            onChange={(event) =>
              patch({
                bucket: event.target.value as InvestmentBucket,
              })
            }
          >
            {BUCKETS.map((item) => (
              <option value={item.value} key={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        ) : (
          <span className="muted-cell">—</span>
        )}
      </td>
      <td>
        <label className="cashflow-check">
          <input
            type="checkbox"
            checked={transaction.is_one_off}
            disabled={saving}
            onChange={(event) =>
              patch({ is_one_off: event.target.checked })
            }
          />
          一次性
        </label>
      </td>
      <td>
        <span className="role-tag">{SOURCE_LABELS[transaction.source] ?? transaction.source}</span>
      </td>
    </tr>
  )
}

export default function CashflowTransactionsTable({
  transactions,
  total,
  onChanged,
}: {
  transactions: CashflowTransaction[]
  total: number
  onChanged: () => void
}) {
  const [direction, setDirection] = useState('')
  const filtered = direction
    ? transactions.filter((item) => item.direction === direction)
    : transactions

  return (
    <section className="card cashflow-table-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">交易明细</h2>
          <p className="card-sub">
            共 {total} 笔；这里显示最近 {transactions.length} 笔。改方向或分类后立即重算汇总。
          </p>
        </div>
        <div className="cashflow-filter">
          <label>
            方向
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value)}
            >
              <option value="">全部</option>
              {DIRECTIONS.map((item) => (
                <option value={item.value} key={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {transactions.length === 0 ? (
        <div className="empty-inline">
          还没有交易。先在上方导入支付宝、微信或银行流水。
        </div>
      ) : (
        <div className="table-scroll">
          <table className="mini-table cashflow-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>金额（原值）</th>
                <th>对方 / 摘要</th>
                <th>方向</th>
                <th>分类</th>
                <th>投资桶</th>
                <th>一次性</th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((transaction) => (
                <TransactionRow
                  key={transaction.id}
                  transaction={transaction}
                  onChanged={onChanged}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="form-note">
        此表金额是账单原始金额（名义）；月度汇总、图表和回填假设按 2% 通胀折算为今日购买力。
        投资买入/卖出不计入消费支出；内部转账默认不计收支。
      </p>
    </section>
  )
}
