import { useState } from 'react'
import type { CalibrationSnapshot, RunResponse } from '../types'
import { createSimpleRun } from '../api'
import { fmtMoney, fmtPct } from '../format'
import { Field, NumberInput, PercentInput, WanInput } from './inputs'
import StatTile from './StatTile'
import FanChart from './FanChart'
import DrawdownChart from './DrawdownChart'
import AnalysisPanel from './AnalysisPanel'

const SIMPLE_PATHS = 5000
const SIMPLE_SEED = 42

const DEFAULT_WEIGHTS: Record<string, number> = {
  csi300: 0.32,
  csi500: 0.16,
  dividend: 0.16,
  sse: 0,
  sp500: 0,
  ndx100: 0.16,
  nikkei: 0,
  hsi: 0,
  gold: 0.04,
  bond: 0.16,
  cash: 0,
}

const roleLabels: Record<string, string> = {
  growth: '成长',
  defensive: '防御',
  cash: '现金',
  illiquid: '非流动',
}

function calibrationWindow(calibration: CalibrationSnapshot): string {
  return (
    (calibration.correlations['10y'] ? '10y' : Object.keys(calibration.correlations)[0]) ??
    '10y'
  )
}

function defaultWeights(calibration: CalibrationSnapshot): Record<string, number> {
  const names = calibration.asset_order
  const raw: Record<string, number> = {}
  let total = 0
  for (const name of names) {
    const value = DEFAULT_WEIGHTS[name] ?? 0
    raw[name] = value
    total += value
  }
  if (total <= 0) {
    const equal = 1 / names.length
    for (const name of names) raw[name] = equal
    return raw
  }
  for (const name of names) raw[name] = raw[name] / total
  return raw
}

function windowLabel(window: string): string {
  return (
    {
      '5y': '近 5 年',
      '10y': '近 10 年',
      '15y': '近 15 年',
      full: '全历史',
    }[window] ?? window
  )
}

export default function SimpleView({
  calibration,
}: {
  calibration: CalibrationSnapshot
}) {
  const windowKey = calibrationWindow(calibration)
  const [initialCapital, setInitialCapital] = useState(100_000)
  const [monthlyContribution, setMonthlyContribution] = useState(5_000)
  const [horizonYears, setHorizonYears] = useState(10)
  const [goalAmount, setGoalAmount] = useState(1_000_000)
  const [weights, setWeights] = useState<Record<string, number>>(() =>
    defaultWeights(calibration),
  )
  const [result, setResult] = useState<RunResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const totalWeight = calibration.asset_order.reduce(
    (sum, name) => sum + (weights[name] ?? 0),
    0,
  )

  const setWeight = (name: string, value: number) => {
    setWeights((previous) => ({ ...previous, [name]: value }))
  }

  const resetWeights = () => setWeights(defaultWeights(calibration))

  const equalWeights = () => {
    const nonCash = calibration.asset_order.filter((name) => name !== 'cash')
    const names = nonCash.length > 0 ? nonCash : calibration.asset_order
    const equal = 1 / names.length
    const next: Record<string, number> = {}
    for (const name of calibration.asset_order) {
      next[name] = names.includes(name) ? equal : 0
    }
    setWeights(next)
  }

  const handleRun = async () => {
    if (initialCapital < 0 || monthlyContribution < 0) {
      setError('初始资金和每月投入不能为负数。')
      return
    }
    if (initialCapital <= 0 && monthlyContribution <= 0) {
      setError('初始资金和每月投入至少有一项大于 0。')
      return
    }
    if (Math.abs(totalWeight - 1) > 1e-4) {
      setError(
        `资产配置比例合计必须为 100%，当前为 ${(totalWeight * 100).toFixed(
          1,
        )}%。`,
      )
      return
    }
    if (calibration.asset_order.some((name) => (weights[name] ?? 0) < 0)) {
      setError('资产配置比例不能为负数。')
      return
    }

    const normalized: Record<string, number> = {}
    for (const name of calibration.asset_order) {
      normalized[name] = (weights[name] ?? 0) / totalWeight
    }

    setBusy(true)
    setError(null)
    try {
      const run = await createSimpleRun({
        name: '简版定投',
        initial_capital: initialCapital,
        monthly_contribution: monthlyContribution,
        horizon_years: horizonYears,
        weights: normalized,
        goal_amount: goalAmount,
        calibration_window: windowKey,
        n_paths: SIMPLE_PATHS,
        seed: SIMPLE_SEED,
      })
      setResult(run)
      window.setTimeout(() => {
        document
          .getElementById('simple-results')
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 60)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const terminal = result?.metrics.terminal_assets
  const goal = result?.metrics.goal_amount ?? 0
  const goalProbability = result?.metrics.goal_probability ?? 0
  const goalLow = result?.metrics.goal_ci95_low ?? 0
  const goalHigh = result?.metrics.goal_ci95_high ?? 0
  const resultYears = result?.request.horizon_years ?? horizonYears
  const resultMonthly =
    result?.request.household.monthly_income ?? monthlyContribution
  const invested =
    (result?.metrics.initial_capital ?? initialCapital) +
    (result?.metrics.total_contributions ?? 0)

  return (
    <div className="simple-page">
      <form
        className="card simple-setup"
        onSubmit={(event) => {
          event.preventDefault()
          handleRun()
        }}
      >
        <div className="setup-head">
          <div>
            <h2 className="card-title">简版定投</h2>
            <p className="card-sub">
              只保留初始资金、每月投入、资产配置和年限；计算沿用历史校准与现有
              蒙特卡洛引擎。
            </p>
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy}
          >
            {busy ? '计算中…' : '开始推演'}
          </button>
        </div>

        <div className="inflation-note">
          已按 2% 通胀折算 · 全部金额为今日购买力（实际口径），不是名义金额
        </div>

        <div className="field-grid four simple-inputs">
          <Field label="初始资金">
            <WanInput
              value={initialCapital}
              onChange={setInitialCapital}
            />
          </Field>
          <Field label="每月投入">
            <WanInput
              value={monthlyContribution}
              onChange={setMonthlyContribution}
            />
          </Field>
          <Field label="推演年限" hint="按月推演">
            <NumberInput
              value={horizonYears}
              step={1}
              min={1}
              max={50}
              suffix="年"
              onChange={setHorizonYears}
            />
          </Field>
          <Field label="目标金额（可选）" hint="0 表示不计算达成概率">
            <WanInput value={goalAmount} onChange={setGoalAmount} />
          </Field>
        </div>

        <div className="section-head simple-assets-head">
          <h3>资产配置</h3>
          <span className="section-note">
            {windowLabel(windowKey)}历史校准 · 合计{' '}
            {(totalWeight * 100).toFixed(1)}%
          </span>
        </div>
        <div className="table-scroll">
          <table className="mini-table holdings-table simple-assets">
            <thead>
              <tr>
                <th>资产</th>
                <th>角色</th>
                <th>实际收益</th>
                <th>波动率</th>
                <th>配置比例</th>
              </tr>
            </thead>
            <tbody>
              {calibration.asset_order.map((name) => {
                const meta = calibration.assets[name]
                const stats = meta?.windows[windowKey]
                return (
                  <tr key={name}>
                    <td>
                      <strong>{meta?.label ?? name}</strong>
                      {stats?.is_short ? (
                        <span className="role-tag warning-tag">历史不足</span>
                      ) : null}
                    </td>
                    <td>
                      <span className="role-tag">
                        {roleLabels[meta?.role ?? 'growth']}
                      </span>
                    </td>
                    <td>
                      {stats ? `${(stats.real_geo * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td>
                      {stats ? `${(stats.volatility * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td>
                      <PercentInput
                        value={weights[name] ?? 0}
                        onChange={(value) => setWeight(name, value)}
                      />
                    </td>
                  </tr>
                )
              })}
              <tr>
                <td colSpan={4}>
                  <strong>合计</strong>
                </td>
                <td>
                  <strong>{(totalWeight * 100).toFixed(1)}%</strong>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="inline-row spaced simple-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={resetWeights}
          >
            恢复默认组合
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={equalWeights}
          >
            非现金等权
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? '计算中…' : '开始推演'}
          </button>
          <span className="form-note">
            每月投入按目标权重建仓，年度再平衡；未计交易成本。
          </span>
        </div>
        <p className="form-note">
          收益、波动和相关性来自{windowLabel(windowKey)}官方全收益/财富指数校准，
          不是预测；资产收益未扣产品费率。简版固定使用 {SIMPLE_PATHS.toLocaleString()}{' '}
          条路径和随机种子 {SIMPLE_SEED}，不包含应急金、负债和人生事件；
          AI 分析与建议可在结果页按需生成。上证指数、日经225、恒生指数的历史
          为“官方全收益 + ETF复权补长”，详见完整版的校准来源。
        </p>
      </form>

      {error ? (
        <div className="error-box">
          <strong>无法完成</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <div id="simple-results">
        {result && terminal ? (
          <div className="results simple-results">
            <div className="simple-result-head">
              <div>
                <h2 className="card-title">推演结果</h2>
                <p className="card-sub">
                  初始 {fmtMoney(result.metrics.initial_capital)} · 每月{' '}
                  {fmtMoney(resultMonthly)} · 累计投入{' '}
                  {fmtMoney(invested)} · {resultYears} 年
                </p>
              </div>
              <span className="run-ref">run {result.run_id}</span>
            </div>

            <div className="metric-grid">
              <StatTile
                hero
                label="期末资产中位数"
                value={fmtMoney(terminal.p50)}
                sub={`${resultYears} 年末 · 5–95 分位 ${fmtMoney(
                  terminal.p5,
                )}–${fmtMoney(terminal.p95)}`}
              />
              <StatTile
                label="5 分位"
                value={fmtMoney(terminal.p5)}
                sub="较差 5% 路径"
              />
              <StatTile
                label="25 分位"
                value={fmtMoney(terminal.p25)}
                sub="下四分位"
              />
              <StatTile
                label="75 分位"
                value={fmtMoney(terminal.p75)}
                sub="上四分位"
              />
              <StatTile
                label="95 分位"
                value={fmtMoney(terminal.p95)}
                sub="较好 5% 路径"
              />
              {goal > 0 ? (
                <StatTile
                  label="目标达成概率"
                  value={fmtPct(goalProbability)}
                  sub={`期末资产 ≥ ${fmtMoney(goal)} · 95% CI ${fmtPct(
                    goalLow,
                  )}–${fmtPct(goalHigh)}`}
                />
              ) : null}
            </div>

            <FanChart run={result} simple />
            <DrawdownChart run={result} />
            <AnalysisPanel mode="simple" runId={result.run_id} />

            <p className="chart-footnote">
              期末资产是今日购买力；分位数为逐时点边际分布，不代表单条路径始终落在带内。
              目标达成概率按期末金融资产 ≥ 目标金额计算。历史校准和固定种子只用于情景推演，
              不构成收益预测或投资建议。
            </p>
          </div>
        ) : (
          <div className="empty-card simple-empty">
            <div className="empty-mark">DCA</div>
            <h2>填写后开始推演</h2>
            <p>
              初始资金、每月投入和资产配置就足够了。结果会给期末资产分位、
              分位路径和最大回撤分布；填了目标金额再额外给出达成概率。
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
