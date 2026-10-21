import { useEffect, useState } from 'react'
import type {
  HistoryMetaResponse,
  HistoryMode,
  HistoryRebalance,
  HistoryResponse,
} from '../types'
import { createHistoryBacktest, getHistoryMeta } from '../api'
import { fmtMoney, fmtPct } from '../format'
import { Field, NumberInput, PercentInput, WanInput } from './inputs'
import StatTile from './StatTile'
import HistoryPathChart from './HistoryPathChart'

const DEFAULT_WEIGHTS: Record<string, number> = {
  csi300: 0.35,
  csi500: 0.15,
  dividend: 0.15,
  ndx100: 0.15,
  gold: 0.05,
  bond: 0.15,
}

function defaultWeights(meta: HistoryMetaResponse): Record<string, number> {
  const result: Record<string, number> = {}
  let total = 0
  for (const asset of meta.assets) {
    const value = DEFAULT_WEIGHTS[asset.name] ?? 0
    result[asset.name] = value
    total += value
  }
  if (total <= 0) {
    const equal = 1 / meta.assets.length
    for (const asset of meta.assets) result[asset.name] = equal
    return result
  }
  for (const asset of meta.assets) result[asset.name] = result[asset.name] / total
  return result
}

function shiftYears(value: string, years: number): string {
  if (!value) return ''
  const parsed = new Date(`${value}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return ''
  parsed.setFullYear(parsed.getFullYear() + years)
  return parsed.toISOString().slice(0, 10)
}

export default function HistoryView() {
  const [meta, setMeta] = useState<HistoryMetaResponse | null>(null)
  const [metaError, setMetaError] = useState<string | null>(null)
  const [historyMode, setHistoryMode] = useState<HistoryMode>('single')
  const [asset, setAsset] = useState('gold')
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [initialCapital, setInitialCapital] = useState(100_000)
  const [monthlyContribution, setMonthlyContribution] = useState(5_000)
  const [rangeMode, setRangeMode] = useState<'lookback' | 'custom'>('lookback')
  const [lookbackYears, setLookbackYears] = useState(10)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [rebalance, setRebalance] = useState<HistoryRebalance>('annual')
  const [result, setResult] = useState<HistoryResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    getHistoryMeta()
      .then((payload) => {
        if (!alive) return
        setMeta(payload)
        setWeights(defaultWeights(payload))
        setEndDate(payload.latest_date)
        if (!payload.assets.some((item) => item.name === 'gold')) {
          setAsset(payload.assets[0]?.name ?? 'csi300')
        }
      })
      .catch((err) => {
        if (alive) setMetaError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      alive = false
    }
  }, [])

  const totalWeight = meta
    ? meta.assets.reduce((sum, item) => sum + (weights[item.name] ?? 0), 0)
    : 0

  const selectedAsset = meta?.assets.find((item) => item.name === asset)

  const activeStarts = meta
    ? historyMode === 'single'
      ? [selectedAsset?.start ?? meta.assets[0]?.start ?? '']
      : meta.assets
          .filter((item) => (weights[item.name] ?? 0) > 0)
          .map((item) => item.start)
    : []
  const minDate =
    activeStarts.length > 0
      ? activeStarts.reduce((latest, value) =>
          value > latest ? value : latest,
        )
      : meta?.assets[0]?.start ?? ''

  const setWeight = (name: string, value: number) => {
    setWeights((previous) => ({ ...previous, [name]: value }))
  }

  const resetWeights = () => {
    if (meta) setWeights(defaultWeights(meta))
  }

  const equalWeights = () => {
    if (!meta) return
    const count = meta.assets.length
    const equal = 1 / count
    const next: Record<string, number> = {}
    for (const item of meta.assets) next[item.name] = equal
    setWeights(next)
  }

  const changeRangeMode = (next: 'lookback' | 'custom') => {
    setRangeMode(next)
    if (next === 'custom' && !startDate && endDate) {
      setStartDate(shiftYears(endDate, -10))
    }
  }

  const handleRun = async () => {
    if (!meta) return
    if (initialCapital < 0 || monthlyContribution < 0) {
      setError('初始资金和每月投入不能为负数。')
      return
    }
    if (initialCapital <= 0 && monthlyContribution <= 0) {
      setError('初始资金和每月投入至少有一项大于 0。')
      return
    }
    if (historyMode === 'portfolio' && Math.abs(totalWeight - 1) > 1e-4) {
      setError(
        `组合配置比例合计必须为 100%，当前为 ${(totalWeight * 100).toFixed(
          1,
        )}%。`,
      )
      return
    }
    if (rangeMode === 'custom') {
      if (!startDate || !endDate) {
        setError('自定义区间需要填写开始日期和结束日期。')
        return
      }
      if (startDate >= endDate) {
        setError('开始日期必须早于结束日期。')
        return
      }
    }

    const normalized: Record<string, number> = {}
    if (historyMode === 'portfolio') {
      for (const item of meta.assets) {
        normalized[item.name] = (weights[item.name] ?? 0) / totalWeight
      }
    }

    setBusy(true)
    setError(null)
    try {
      const payload = await createHistoryBacktest({
        mode: historyMode,
        asset,
        weights: historyMode === 'portfolio' ? normalized : {},
        initial_capital: initialCapital,
        monthly_contribution: monthlyContribution,
        start_date: rangeMode === 'custom' ? startDate : null,
        end_date: endDate || null,
        lookback_years: rangeMode === 'lookback' ? lookbackYears : null,
        rebalance,
      })
      setResult(payload)
      window.setTimeout(() => {
        document
          .getElementById('history-results')
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 60)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!meta) {
    return (
      <div className="loading-card">
        {metaError ? (
          <>
            <strong>加载历史数据失败</strong>
            <p>{metaError}</p>
          </>
        ) : (
          '正在加载历史全收益数据…'
        )}
      </div>
    )
  }

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
            <h2 className="card-title">历史定投回测</h2>
            <p className="card-sub">
              用官方全收益指数的日频真实数据，回测一段历史区间内每月定投的结果。
            </p>
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? '计算中…' : '开始回测'}
          </button>
        </div>

        <div className="inflation-note">
          已按 {(meta.inflation_assumption * 100).toFixed(0)}%
          通胀折算 · 全部金额为今日购买力（实际口径），不是名义金额
        </div>

        <div className="field-grid four simple-inputs">
          <Field label="定投方式">
            <select
              value={historyMode}
              onChange={(event) =>
                setHistoryMode(event.target.value as HistoryMode)
              }
            >
              <option value="single">单资产</option>
              <option value="portfolio">多资产组合</option>
            </select>
          </Field>
          {historyMode === 'single' ? (
            <Field label="资产">
              <select
                value={asset}
                onChange={(event) => setAsset(event.target.value)}
              >
                {meta.assets.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label="再平衡">
              <select
                value={rebalance}
                onChange={(event) =>
                  setRebalance(event.target.value as HistoryRebalance)
                }
              >
                <option value="annual">年度再平衡</option>
                <option value="none">不再平衡</option>
              </select>
            </Field>
          )}
          <Field label="初始资金">
            <WanInput value={initialCapital} onChange={setInitialCapital} />
          </Field>
          <Field label="每月投入">
            <WanInput
              value={monthlyContribution}
              onChange={setMonthlyContribution}
            />
          </Field>
        </div>

        <div className="field-grid four simple-inputs">
          <Field label="区间方式">
            <select
              value={rangeMode}
              onChange={(event) =>
                changeRangeMode(event.target.value as 'lookback' | 'custom')
              }
            >
              <option value="lookback">过去 N 年</option>
              <option value="custom">自定义起止日期</option>
            </select>
          </Field>
          {rangeMode === 'lookback' ? (
            <Field label="过去 N 年">
              <NumberInput
                value={lookbackYears}
                step={1}
                min={1}
                max={50}
                suffix="年"
                onChange={setLookbackYears}
              />
            </Field>
          ) : (
            <Field label="开始日期">
              <input
                type="date"
                value={startDate}
                min={minDate}
                max={meta.latest_date}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </Field>
          )}
          <Field label="结束日期">
            <input
              type="date"
              value={endDate}
              min={minDate}
              max={meta.latest_date}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </Field>
          <span className="form-note self-end">
            数据截至 {meta.latest_date}；实际区间会按资产可用日期自动裁剪。
          </span>
        </div>

        {historyMode === 'single' && selectedAsset ? (
          <p className="form-note">
            {selectedAsset.label} · {selectedAsset.source} · 数据{' '}
            {selectedAsset.start}–{selectedAsset.end}
          </p>
        ) : null}

        {historyMode === 'portfolio' ? (
          <>
            <div className="section-head simple-assets-head">
              <h3>组合配置</h3>
              <span className="section-note">
                合计 {(totalWeight * 100).toFixed(1)}% · 0% 表示不配置
              </span>
            </div>
            <div className="table-scroll">
              <table className="mini-table holdings-table simple-assets">
                <thead>
                  <tr>
                    <th>资产</th>
                    <th>数据起点</th>
                    <th>配置比例</th>
                  </tr>
                </thead>
                <tbody>
                  {meta.assets.map((item) => (
                    <tr key={item.name}>
                      <td>
                        <strong>{item.label}</strong>
                      </td>
                      <td>{item.start}</td>
                      <td>
                        <PercentInput
                          value={weights[item.name] ?? 0}
                          onChange={(value) => setWeight(item.name, value)}
                        />
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <td colSpan={2}>
                      <strong>合计</strong>
                    </td>
                    <td>
                      <strong>{(totalWeight * 100).toFixed(1)}%</strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="simple-actions">
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
                等权
              </button>
            </div>
          </>
        ) : null}

        <div className="simple-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? '计算中…' : '开始回测'}
          </button>
          <span className="form-note">
            每月第一个交易日投入；初始资金与第一次月投入同时进入。
            {historyMode === 'portfolio'
              ? rebalance === 'annual'
                ? ' 每年首个交易日再平衡，未计交易成本。'
                : ' 不再平衡。'
              : ''}
          </span>
        </div>

        <p className="form-note">
          历史回测使用官方全收益/财富指数，已按 {(
            meta.inflation_assumption * 100
          ).toFixed(0)}
          % 通胀折算成今日购买力；官方指数未扣产品费率。黄金为 2006-01
          起的 COMEX×汇率人民币金价，纳指人民币从 2010-01 开始，长区间会自动裁剪。
        </p>
      </form>

      {error ? (
        <div className="error-box">
          <strong>无法完成</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <div id="history-results">
        {result ? (
          <div className="results simple-results">
            {result.warnings.length > 0 ? (
              <div className="warning-box">
                {result.warnings.map((warning, index) => (
                  <div key={index}>{warning}</div>
                ))}
              </div>
            ) : null}

            <div className="simple-result-head">
              <div>
                <h2 className="card-title">回测结果</h2>
                <p className="card-sub">
                  {result.request.mode === 'single'
                    ? result.final_composition[0]?.label
                    : '多资产组合'}{' '}
                  · {result.effective_start_date}–{result.effective_end_date} ·
                  每月 {fmtMoney(result.monthly_contribution)} · 共{' '}
                  {result.contribution_count} 次 · 今日购买力（已按 2% 通胀折算）
                </p>
              </div>
              <span className="run-ref">history {result.run_id}</span>
            </div>

            <div className="metric-grid">
              <StatTile
                hero
                label="期末总资产"
                value={fmtMoney(result.terminal_value)}
                sub={`实际区间 ${result.effective_start_date}–${result.effective_end_date}`}
              />
              <StatTile
                label="累计投入"
                value={fmtMoney(result.total_invested)}
                sub={`初始 ${fmtMoney(result.initial_capital)} + 每月 ${fmtMoney(
                  result.monthly_contribution,
                )} × ${result.contribution_count} 次`}
              />
              <StatTile
                label="收益"
                value={fmtMoney(result.profit)}
                sub={`收益率 ${fmtPct(result.return_on_invested)}`}
              />
              <StatTile
                label="实际年化 IRR"
                value={
                  result.irr_annual !== null
                    ? fmtPct(result.irr_annual)
                    : '—'
                }
                sub="货币加权 · 今日购买力"
              />
              <StatTile
                label="最大回撤（TWR）"
                value={fmtPct(result.max_drawdown)}
                sub={
                  result.drawdown_peak_date && result.drawdown_trough_date
                    ? `${result.drawdown_peak_date} → ${result.drawdown_trough_date}`
                    : '—'
                }
              />
              <StatTile
                label="定投次数"
                value={`${result.contribution_count} 次`}
                sub={`实际 ${result.months} 个月`}
              />
            </div>

            <HistoryPathChart history={result} />

            {result.final_composition.length > 1 ? (
              <section className="card composition-card">
                <div className="card-head">
                  <div>
                    <h2 className="card-title">期末资产构成</h2>
                    <p className="card-sub">
                      各资产期末实际市值与占比 · 权重会随市场漂移
                    </p>
                  </div>
                </div>
                <div className="table-scroll">
                  <table className="mini-table composition-table">
                    <thead>
                      <tr>
                        <th>资产</th>
                        <th>期末市值</th>
                        <th>占比</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.final_composition.map((item) => (
                        <tr key={item.asset}>
                          <td>{item.label}</td>
                          <td>{fmtMoney(item.value)}</td>
                          <td>{fmtPct(item.weight)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}

            <p className="chart-footnote">
              历史回测是已实现路径，不是未来预测；过去表现不代表未来。
              全部金额为今日购买力，已按 2% 通胀折算；未计交易费用、税费和产品费率。
              最大回撤按时间加权单位净值计算，剔除每月投入的影响。
            </p>
          </div>
        ) : (
          <div className="empty-card simple-empty">
            <div className="empty-mark">HIST</div>
            <h2>选一段真实历史，看定投结果</h2>
            <p>
              例如黄金、沪深300 或一个多资产组合。默认“过去 10
              年”，也可以自定义起止日期；结果会给出期末总资产、累计投入、收益、
              货币加权 IRR、最大回撤和逐年路径。
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
