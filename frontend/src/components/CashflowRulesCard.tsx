import { useState } from 'react'
import type {
  CashflowDirection,
  CashflowRule,
  CashflowRuleInput,
  InvestmentBucket,
} from '../types'
import {
  createCashflowRule,
  deleteCashflowRule,
  reapplyCashflowRules,
} from '../api'

const DIRECTIONS: { value: CashflowDirection; label: string }[] = [
  { value: 'income', label: '收入' },
  { value: 'expense', label: '支出' },
  { value: 'investment', label: '投资' },
  { value: 'transfer', label: '转账' },
  { value: 'ignore', label: '不计' },
]

const BUCKETS: { value: InvestmentBucket; label: string }[] = [
  { value: 'cash', label: '现金/货币' },
  { value: 'a_share', label: 'A股基金' },
  { value: 'overseas', label: '海外基金' },
  { value: 'gold', label: '黄金' },
  { value: 'bond', label: '债券' },
  { value: 'other', label: '其他' },
]

const EMPTY: CashflowRuleInput = {
  priority: 200,
  pattern: '',
  match_field: 'any',
  direction: 'expense',
  category: '其他支出',
  bucket: null,
  investment_action: null,
  enabled: true,
  note: '',
}

export default function CashflowRulesCard({
  rules,
  onChanged,
}: {
  rules: CashflowRule[]
  onChanged: () => void
}) {
  const [draft, setDraft] = useState<CashflowRuleInput>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const update = (patch: Partial<CashflowRuleInput>) =>
    setDraft((previous) => ({ ...previous, ...patch }))

  const add = async () => {
    if (!draft.pattern.trim() || !draft.category.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createCashflowRule({
        ...draft,
        pattern: draft.pattern.trim(),
        category: draft.category.trim(),
      })
      setDraft(EMPTY)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const reapply = async () => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await reapplyCashflowRules()
      setMessage(`已重新分类 ${result.updated} 笔交易；手动修改过的交易保持不变。`)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    setBusy(true)
    try {
      await deleteCashflowRule(id)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card cashflow-rules-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">分类规则</h2>
          <p className="card-sub">
            关键词先匹配高优先级规则；手动改过的交易不会被规则覆盖。规则只影响之后重新导入/手动重分类。
          </p>
        </div>
      </div>

      <div className="cashflow-rule-add">
        <input
          value={draft.pattern}
          placeholder="关键词，如 星巴克"
          onChange={(event) => update({ pattern: event.target.value })}
        />
        <select
          value={draft.match_field}
          onChange={(event) =>
            update({
              match_field: event.target
                .value as CashflowRuleInput['match_field'],
            })
          }
        >
          <option value="any">对方+摘要+原分类</option>
          <option value="counterparty">交易对方</option>
          <option value="description">商品/摘要</option>
          <option value="category">原始分类</option>
        </select>
        <select
          value={draft.direction ?? ''}
          onChange={(event) =>
            update({
              direction: (event.target.value || null) as CashflowDirection | null,
            })
          }
        >
          <option value="">不改方向</option>
          {DIRECTIONS.map((item) => (
            <option value={item.value} key={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <input
          value={draft.category}
          placeholder="分类，如 餐饮"
          onChange={(event) => update({ category: event.target.value })}
        />
        <select
          value={draft.bucket ?? ''}
          onChange={(event) =>
            update({
              bucket: (event.target.value || null) as InvestmentBucket | null,
            })
          }
        >
          <option value="">不设投资桶</option>
          {BUCKETS.map((item) => (
            <option value={item.value} key={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <input
          type="number"
          value={draft.priority}
          title="优先级"
          onChange={(event) => update({ priority: Number(event.target.value) })}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={add}
        >
          添加规则
        </button>
      </div>
      {error ? <div className="form-note danger">{error}</div> : null}
      <div className="inline-row spaced">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy}
          onClick={reapply}
        >
          重新应用规则
        </button>
        {message ? <span className="form-note">{message}</span> : null}
      </div>

      <details className="table-view">
        <summary>查看/管理规则（{rules.length}）</summary>
        <div className="table-scroll cashflow-rule-table">
          <table className="mini-table">
          <thead>
            <tr>
              <th>优先级</th>
              <th>匹配</th>
              <th>字段</th>
              <th>方向</th>
              <th>分类</th>
              <th>投资桶</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id}>
                <td>{rule.priority}</td>
                <td>
                  <strong>{rule.pattern}</strong>
                </td>
                <td>{rule.match_field}</td>
                <td>
                  {DIRECTIONS.find((item) => item.value === rule.direction)
                    ?.label ?? '不改'}
                </td>
                <td>{rule.category}</td>
                <td>
                  {BUCKETS.find((item) => item.value === rule.bucket)?.label ??
                    '—'}
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-secondary small"
                    disabled={busy}
                    onClick={() => remove(rule.id)}
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
    </section>
  )
}
