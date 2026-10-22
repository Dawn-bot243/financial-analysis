import { useRef, useState } from 'react'
import type { CashflowBalance, InvestmentBucket } from '../types'
import {
  deleteCashflowBalance,
  importCashflowBalances,
  upsertCashflowBalance,
} from '../api'
import { fmtMoney } from '../format'
import { Field, NumberInput } from './inputs'

const BUCKETS: { value: InvestmentBucket; label: string }[] = [
  { value: 'cash', label: '现金/货币' },
  { value: 'a_share', label: 'A股基金' },
  { value: 'overseas', label: '海外基金' },
  { value: 'gold', label: '黄金' },
  { value: 'bond', label: '债券' },
  { value: 'other', label: '其他' },
]

const LABELS = Object.fromEntries(
  BUCKETS.map((item) => [item.value, item.label]),
) as Record<InvestmentBucket, string>

export default function CashflowBalancesCard({
  balances,
  onChanged,
}: {
  balances: CashflowBalance[]
  onChanged: () => void
}) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [bucket, setBucket] = useState<InvestmentBucket>('cash')
  const [balance, setBalance] = useState(0)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const add = async () => {
    if (!date || balance < 0) return
    setBusy(true)
    setMessage(null)
    try {
      await upsertCashflowBalance({ date, bucket, balance, note })
      setBalance(0)
      setNote('')
      onChanged()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    setBusy(true)
    try {
      await deleteCashflowBalance(id)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  const importFile = async (file: File | null) => {
    if (!file) return
    setBusy(true)
    setMessage(null)
    try {
      const result = await importCashflowBalances(file)
      setMessage(
        `导入 ${result.imported} 条，跳过 ${result.skipped} 条。` +
          (result.warnings.length ? ` ${result.warnings.join(' ')}` : ''),
      )
      onChanged()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <section className="card cashflow-balance-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">月度资产余额</h2>
          <p className="card-sub">
            手动填或导入“日期, 资产, 余额”CSV；表格是录入原值，资产配置图按今日购买力折算。
          </p>
        </div>
      </div>

      <div className="cashflow-balance-form">
        <Field label="日期">
          <input
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </Field>
        <Field label="资产桶">
          <select
            value={bucket}
            onChange={(event) =>
              setBucket(event.target.value as InvestmentBucket)
            }
          >
            {BUCKETS.map((item) => (
              <option value={item.value} key={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="余额">
          <NumberInput
            value={balance}
            step={1000}
            min={0}
            suffix="元"
            onChange={setBalance}
          />
        </Field>
        <Field label="备注（可选）">
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="例如月末快照"
          />
        </Field>
        <button
          type="button"
          className="btn btn-primary cashflow-balance-add"
          disabled={busy}
          onClick={add}
        >
          添加/覆盖
        </button>
      </div>

      <div className="inline-row spaced">
        <label className="cashflow-file-link">
          导入余额 CSV
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(event) => importFile(event.target.files?.[0] ?? null)}
          />
        </label>
        {message ? <span className="form-note">{message}</span> : null}
      </div>

      {balances.length === 0 ? (
        <div className="empty-inline">还没有余额快照。至少填一个月末余额。</div>
      ) : (
        <details className="table-view">
          <summary>查看/删除余额快照（{balances.length}）</summary>
          <div className="table-scroll">
            <table className="mini-table cashflow-balance-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>资产桶</th>
                <th>余额（原值）</th>
                <th>来源</th>
                <th>备注</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {balances.map((item) => (
                <tr key={item.id}>
                  <td>{item.date}</td>
                  <td>{LABELS[item.bucket]}</td>
                  <td>{fmtMoney(item.balance)}</td>
                  <td>{item.source}</td>
                  <td>{item.note || '—'}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-secondary small cashflow-delete"
                      disabled={busy}
                      onClick={() => remove(item.id)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  )
}
