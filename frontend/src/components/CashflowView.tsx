import { useEffect, useState } from 'react'
import type {
  CashflowAssumptionPreview,
  CashflowBalance,
  CashflowCategoryTotal,
  CashflowRule,
  CashflowSummary,
  CashflowTransaction,
  InvestmentBucket,
} from '../types'
import {
  getCashflowAssumptions,
  getCashflowSummary,
  listCashflowBalances,
  listCashflowRules,
  listCashflowTransactions,
} from '../api'
import { fmtMoney, fmtPct } from '../format'
import StatTile from './StatTile'
import CashflowImportPanel from './CashflowImportPanel'
import CashflowAssumptionCard from './CashflowAssumptionCard'
import CashflowTransactionsTable from './CashflowTransactionsTable'
import CashflowBalancesCard from './CashflowBalancesCard'
import CashflowRulesCard from './CashflowRulesCard'
import {
  BalanceAllocationChart,
  ExpenseStructureChart,
  InvestmentFlowChart,
  MonthlyFlowChart,
  SavingsRateChart,
} from './CashflowCharts'

const BUCKET_LABELS: Record<InvestmentBucket, string> = {
  cash: '现金/货币',
  a_share: 'A股基金',
  overseas: '海外基金',
  gold: '黄金',
  bond: '债券',
  other: '其他',
}

function CategoryTable({
  title,
  items,
}: {
  title: string
  items: CashflowCategoryTotal[]
}) {
  return (
    <section className="card cashflow-mini-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">{title}</h3>
          <p className="card-sub">今日购买力；占比按总额计算。</p>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="empty-inline">还没有数据。</div>
      ) : (
        <div className="table-scroll">
          <table className="mini-table">
            <thead>
              <tr>
                <th>类别</th>
                <th>金额</th>
                <th>占比</th>
                <th>一次性</th>
                <th>笔数</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.category}>
                  <td>{item.category}</td>
                  <td>{fmtMoney(item.amount)}</td>
                  <td>{fmtPct(item.share)}</td>
                  <td>{item.one_off_amount ? fmtMoney(item.one_off_amount) : '—'}</td>
                  <td>{item.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function InvestmentTable({ summary }: { summary: CashflowSummary }) {
  if (summary.investment_buckets.length === 0) {
    return (
      <section className="card cashflow-mini-card">
        <div className="card-head">
          <div>
            <h3 className="card-title">投资结构</h3>
            <p className="card-sub">把基金/股票/黄金等买入识别为投资，不计入消费支出。</p>
          </div>
        </div>
        <div className="empty-inline">还没有识别到投资交易。</div>
      </section>
    )
  }
  return (
    <section className="card cashflow-mini-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">投资结构</h3>
          <p className="card-sub">买入/卖出/净投入；卖出不冲减买入柱。</p>
        </div>
      </div>
      <div className="table-scroll">
        <table className="mini-table">
          <thead>
            <tr>
              <th>投资桶</th>
              <th>买入</th>
              <th>卖出</th>
              <th>净投入</th>
              <th>买入占比</th>
            </tr>
          </thead>
          <tbody>
            {summary.investment_buckets.map((item) => (
              <tr key={item.bucket}>
                <td>{BUCKET_LABELS[item.bucket]}</td>
                <td>{fmtMoney(item.buy)}</td>
                <td>{item.sell ? fmtMoney(item.sell) : '—'}</td>
                <td>{fmtMoney(item.net)}</td>
                <td>{fmtPct(item.buy_share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function LatestBalanceTable({ summary }: { summary: CashflowSummary }) {
  const entries = Object.entries(summary.latest_balances).filter(
    ([, value]) => value > 0,
  ) as [InvestmentBucket, number][]
  const total = entries.reduce((sum, [, value]) => sum + value, 0)
  if (entries.length === 0) return null
  return (
    <section className="card cashflow-mini-card">
      <div className="card-head">
        <div>
          <h3 className="card-title">最新资产配置</h3>
          <p className="card-sub">
            {summary.balances[summary.balances.length - 1]?.month} 余额快照，今日购买力。
          </p>
        </div>
      </div>
      <div className="table-scroll">
        <table className="mini-table">
          <thead>
            <tr>
              <th>资产桶</th>
              <th>余额</th>
              <th>占比</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([bucket, value]) => (
              <tr key={bucket}>
                <td>{BUCKET_LABELS[bucket]}</td>
                <td>{fmtMoney(value)}</td>
                <td>{fmtPct(total > 0 ? value / total : 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default function CashflowView({
  onApplyAssumptions,
}: {
  onApplyAssumptions: (patch: {
    monthlyIncome: number
    monthlyExpense: number
  }) => void
}) {
  const [summary, setSummary] = useState<CashflowSummary | null>(null)
  const [transactions, setTransactions] = useState<CashflowTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [rules, setRules] = useState<CashflowRule[]>([])
  const [balances, setBalances] = useState<CashflowBalance[]>([])
  const [assumption, setAssumption] =
    useState<CashflowAssumptionPreview | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setBusy(true)
    setError(null)
    try {
      const [nextSummary, transactionPage, nextRules, nextBalances] =
        await Promise.all([
          getCashflowSummary(),
          listCashflowTransactions({ limit: 200 }),
          listCashflowRules(),
          listCashflowBalances(),
        ])
      setSummary(nextSummary)
      setTransactions(transactionPage.items)
      setTotal(transactionPage.total)
      setRules(nextRules)
      setBalances(nextBalances)
      try {
        setAssumption(await getCashflowAssumptions(12))
      } catch {
        setAssumption(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const apply = () => {
    if (!assumption) return
    onApplyAssumptions({
      monthlyIncome: assumption.monthly_income,
      monthlyExpense: assumption.monthly_expense,
    })
  }

  return (
    <div className="cashflow-page">
      <CashflowImportPanel onImported={load} />

      <div className="inflation-note">
        导入明细和余额表保留账单原值；收入/支出汇总、图表和回填假设已按 2%
        通胀折算为今日购买力。
      </div>

      {error ? (
        <div className="error-box">
          <strong>无法读取收支数据</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {busy && !summary ? (
        <div className="loading-card">正在读取本地收支数据…</div>
      ) : null}

      {summary ? (
        summary.transaction_count === 0 && summary.balances.length === 0 ? (
          <>
            <div className="empty-card cashflow-empty">
              <div className="empty-mark">CF</div>
              <h2>先导入历史流水</h2>
              <p>
                支持支付宝、微信、银行 CSV/Excel。导入后先确认字段映射，再在流水表里修正分类；
                资产余额可以手动填或导入月度快照。
              </p>
            </div>
            <div className="cashflow-bottom-grid">
              <CashflowBalancesCard balances={balances} onChanged={load} />
              <CashflowRulesCard rules={rules} onChanged={load} />
            </div>
          </>
        ) : (
        <>
          <div className="metric-grid cashflow-metrics">
            <StatTile
              hero
              label="累计收入"
              value={fmtMoney(summary.total_income)}
              sub={`${summary.from_date ?? '—'} 至 ${summary.to_date ?? '—'}`}
            />
            <StatTile
              label="累计支出"
              value={fmtMoney(summary.total_expense)}
              sub="不含投资买入和内部转账"
            />
            <StatTile
              label="累计结余"
              value={fmtMoney(summary.total_net_savings)}
              sub="收入 - 支出"
            />
            <StatTile
              label="储蓄率"
              value={
                summary.savings_rate !== null
                  ? fmtPct(summary.savings_rate)
                  : '—'
              }
              sub="含一次性收支"
            />
            <StatTile
              label="投资净投入"
              value={fmtMoney(
                summary.investment_buckets.reduce(
                  (sum, item) => sum + item.net,
                  0,
                ),
              )}
              sub="买入 - 卖出"
            />
            <StatTile
              label="交易笔数"
              value={`${summary.transaction_count} 笔`}
              sub={`${summary.months.length} 个月`}
            />
          </div>

          <CashflowAssumptionCard preview={assumption} onApply={apply} />

          {summary.warnings.length > 0 ? (
            <div className="warning-box">
              {summary.warnings.map((warning, index) => (
                <div key={index}>{warning}</div>
              ))}
            </div>
          ) : null}

          <div className="cashflow-chart-grid">
            <MonthlyFlowChart summary={summary} />
            <SavingsRateChart summary={summary} />
            <InvestmentFlowChart summary={summary} />
            <BalanceAllocationChart summary={summary} />
            <ExpenseStructureChart summary={summary} />
          </div>

          <div className="cashflow-table-grid">
            <CategoryTable title="收入结构" items={summary.income_categories} />
            <CategoryTable title="支出结构" items={summary.expense_categories} />
            <InvestmentTable summary={summary} />
            <LatestBalanceTable summary={summary} />
          </div>

          <CashflowTransactionsTable
            transactions={transactions}
            total={total}
            onChanged={load}
          />

          <div className="cashflow-bottom-grid">
            <CashflowBalancesCard balances={balances} onChanged={load} />
            <CashflowRulesCard rules={rules} onChanged={load} />
          </div>
        </>
        )
      ) : null}
    </div>
  )
}
