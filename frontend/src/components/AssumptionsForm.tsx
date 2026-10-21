import type { CalibrationSnapshot } from '../types'
import type {
  AssetForm,
  EventForm,
  EventKind,
  FormState,
  HoldingForm,
  LiabilityForm,
  PathVariant,
  PurchaseForm,
} from '../form'
import { calibrationLabel, newPurchase } from '../form'
import { fmtMoney } from '../format'
import { Field, NumberInput, PercentInput, WanInput } from './inputs'
import Glossary from './Glossary'

interface Props {
  form: FormState
  calibration: CalibrationSnapshot | null
  busy: 'run' | 'compare' | null
  onChange: (patch: Partial<FormState>) => void
  onAssetChange: (index: number, patch: Partial<AssetForm>) => void
  onHoldingChange: (index: number, patch: Partial<HoldingForm>) => void
  onLiabilityChange: (index: number, patch: Partial<LiabilityForm>) => void
  onAddLiability: () => void
  onRemoveLiability: (index: number) => void
  onEventChange: (index: number, patch: Partial<EventForm>) => void
  onPurchaseChange: (index: number, patch: Partial<PurchaseForm>) => void
  onAddEvent: (kind: EventKind) => void
  onRemoveEvent: (index: number) => void
  onAddPathVariant: () => void
  onPathVariantChange: (index: number, patch: Partial<PathVariant>) => void
  onRemovePathVariant: (index: number) => void
  onApplyCalibration: (window: string) => void
  onRun: () => void
  onCompare: () => void
  onRunPathCompare: () => void
}

const roleLabels: Record<string, string> = {
  growth: '成长',
  defensive: '防御',
  cash: '现金',
  illiquid: '非流动',
}

const eventKindLabels: Record<EventKind, string> = {
  one_off: '一次性支出',
  recurring_income: '持续收入',
  recurring_expense: '持续支出',
  purchase: '买入资产',
}

function monthlyPayment(
  balance: number,
  annualRate: number,
  months: number,
): number {
  if (balance <= 0 || months <= 0) return 0
  const rate = annualRate / 12
  if (Math.abs(rate) < 1e-12) return balance / months
  return (balance * rate) / (1 - Math.pow(1 + rate, -months))
}

function NullableNumberInput({
  value,
  onChange,
  step = 1,
  suffix,
}: {
  value: number | null
  onChange: (value: number | null) => void
  step?: number
  suffix?: string
}) {
  return (
    <span className="input-wrap">
      <input
        type="number"
        value={value ?? ''}
        step={step}
        min={0}
        onChange={(event) => {
          const raw = event.target.value
          if (raw.trim() === '') {
            onChange(null)
            return
          }
          const parsed = Number(raw)
          if (Number.isFinite(parsed)) onChange(parsed)
        }}
      />
      {suffix ? <span className="unit">{suffix}</span> : null}
    </span>
  )
}

function EventCard({
  event,
  index,
  form,
  onEventChange,
  onPurchaseChange,
  onRemoveEvent,
}: {
  event: EventForm
  index: number
  form: FormState
  onEventChange: (index: number, patch: Partial<EventForm>) => void
  onPurchaseChange: (index: number, patch: Partial<PurchaseForm>) => void
  onRemoveEvent: (index: number) => void
}) {
  const purchase = event.purchase
  return (
    <div className="event-card">
      <div className="event-card-head">
        <Field label="事件类型">
          <select
            value={event.kind}
            onChange={(changeEvent) => {
              const kind = changeEvent.target.value as EventKind
              if (kind === 'purchase' && !event.purchase) {
                onEventChange(index, {
                  kind,
                  purchase: newPurchase('real_estate', event.startAge),
                })
              } else {
                onEventChange(index, { kind })
              }
            }}
          >
            {Object.entries(eventKindLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="名称">
          <input
            type="text"
            value={event.name}
            onChange={(changeEvent) =>
              onEventChange(index, { name: changeEvent.target.value })
            }
          />
        </Field>
        <Field
          label={
            event.kind === 'purchase' || event.kind === 'one_off'
              ? '最早年龄'
              : '开始年龄'
          }
        >
          <NumberInput
            value={event.startAge}
            step={0.5}
            min={0}
            suffix="岁"
            onChange={(value) => onEventChange(index, { startAge: value })}
          />
        </Field>
        {event.kind === 'purchase' || event.kind === 'one_off' ? (
          <Field label="时间窗" hint="0=单月；3=3年">
            <NumberInput
              value={event.windowYears}
              step={1}
              min={0}
              max={30}
              suffix="年"
              onChange={(value) => onEventChange(index, { windowYears: value })}
            />
          </Field>
        ) : null}
        {event.kind !== 'one_off' ? (
          <Field
            label={
              event.kind === 'purchase'
                ? '持续收支到（可选）'
                : '持续到（可选）'
            }
          >
            <NullableNumberInput
              value={event.endAge}
              step={0.5}
              suffix="岁"
              onChange={(value) => onEventChange(index, { endAge: value })}
            />
          </Field>
        ) : null}
        <button
          type="button"
          className="icon-btn"
          aria-label="删除事件"
          onClick={() => onRemoveEvent(index)}
        >
          ×
        </button>
      </div>

      {event.kind === 'one_off' ? (
        <>
          <div className="field-grid">
            <Field label="一次性支出">
              <WanInput
                value={event.oneOffExpense}
                onChange={(value) =>
                  onEventChange(index, { oneOffExpense: value })
                }
              />
            </Field>
          </div>
          <p className="form-note">
            时间窗内每月用全部流动资产（投资资产 + 现金 + 应急金）检查一次；
            首次付得起时支付；窗口末月仍不足时赎回全部流动资产并记录缺口。
            时间窗为 0 时只在最早年龄支付。
          </p>
        </>
      ) : null}

      {event.kind === 'recurring_income' ? (
        <div className="field-grid">
          <Field label="每月收入">
            <WanInput
              value={event.monthlyIncome}
              onChange={(value) => onEventChange(index, { monthlyIncome: value })}
            />
          </Field>
        </div>
      ) : null}

      {event.kind === 'recurring_expense' ? (
        <div className="field-grid">
          <Field label="每月支出">
            <WanInput
              value={event.monthlyExpense}
              onChange={(value) => onEventChange(index, { monthlyExpense: value })}
            />
          </Field>
        </div>
      ) : null}

      {event.kind === 'purchase' && purchase ? (
        <>
          <div className="field-grid">
            <Field label="资产类型">
              <select
                value={purchase.asset}
                onChange={(changeEvent) =>
                  onPurchaseChange(index, { asset: changeEvent.target.value })
                }
              >
                <option value="real_estate">房产</option>
                <option value="car">车</option>
                <option value="other_illiquid">其他资产</option>
              </select>
            </Field>
            <Field label="资产名称">
              <input
                type="text"
                value={purchase.label}
                onChange={(changeEvent) =>
                  onPurchaseChange(index, { label: changeEvent.target.value })
                }
              />
            </Field>
            <Field label="总价">
              <WanInput
                value={purchase.price}
                onChange={(value) => onPurchaseChange(index, { price: value })}
              />
            </Field>
            <Field label="首付">
              <WanInput
                value={purchase.downPayment}
                onChange={(value) =>
                  onPurchaseChange(index, { downPayment: value })
                }
              />
            </Field>
            <Field label="贷款利率">
              <PercentInput
                value={purchase.loanRate}
                onChange={(value) => onPurchaseChange(index, { loanRate: value })}
              />
            </Field>
            <Field label="贷款期数">
              <NumberInput
                value={purchase.loanMonths}
                step={12}
                min={0}
                suffix="月"
                onChange={(value) =>
                  onPurchaseChange(index, { loanMonths: value })
                }
              />
            </Field>
            <Field label="年增值/折旧">
              <PercentInput
                value={purchase.appreciationRate}
                onChange={(value) =>
                  onPurchaseChange(index, { appreciationRate: value })
                }
              />
            </Field>
            <Field label="月租金/收入">
              <WanInput
                value={purchase.monthlyRent}
                onChange={(value) =>
                  onPurchaseChange(index, { monthlyRent: value })
                }
              />
            </Field>
            <Field label="月维护/持有支出">
              <WanInput
                value={event.monthlyExpense}
                onChange={(value) =>
                  onEventChange(index, { monthlyExpense: value })
                }
              />
            </Field>
            <Field label="卖出费率">
              <PercentInput
                value={purchase.sellingCostRate}
                onChange={(value) =>
                  onPurchaseChange(index, { sellingCostRate: value })
                }
              />
            </Field>
            <Field label="卖出年龄（可选）">
              <NullableNumberInput
                value={purchase.sellAge}
                step={0.5}
                suffix="岁"
                onChange={(value) =>
                  onPurchaseChange(index, { sellAge: value })
                }
              />
            </Field>
            <Field label="交易费用/税费">
              <WanInput
                value={event.oneOffExpense}
                onChange={(value) =>
                  onEventChange(index, { oneOffExpense: value })
                }
              />
            </Field>
          </div>
          <p className="form-note">
            时间窗内每月用全部流动资产（投资资产 + 现金 + 应急金）检查一次；
            首次买得起时买入；窗口末月会再试一次，仍不足则记未通过，不会自动卖出房产等非流动资产。
            窗口内的买入价和首付按“年增值/折旧”折算。卖出所得先补足应急金，再投入金融资产。
          </p>
        </>
      ) : null}
    </div>
  )
}

export default function AssumptionsForm({
  form,
  calibration,
  busy,
  onChange,
  onAssetChange,
  onHoldingChange,
  onLiabilityChange,
  onAddLiability,
  onRemoveLiability,
  onEventChange,
  onPurchaseChange,
  onAddEvent,
  onRemoveEvent,
  onAddPathVariant,
  onPathVariantChange,
  onRemovePathVariant,
  onApplyCalibration,
  onRun,
  onCompare,
  onRunPathCompare,
}: Props) {
  const liquidHoldings = form.holdings.filter(
    (holding) => holding.liquidity === 'liquid',
  )
  const liquidTotal = liquidHoldings.reduce(
    (sum, holding) => sum + holding.value,
    0,
  )
  const cashHolding =
    liquidHoldings.find((holding) => holding.asset === form.cashAsset)?.value ??
    0
  const debtPayment = form.liabilities.reduce(
    (sum, liability) =>
      sum +
      monthlyPayment(
        liability.balance,
        liability.annualRate,
        liability.remainingMonths,
      ),
    0,
  )
  const illiquidIncome = form.holdings
    .filter((holding) => holding.liquidity === 'illiquid')
    .reduce((sum, holding) => sum + holding.monthlyIncome, 0)
  const emergencyTarget =
    form.emergencyMonths *
    Math.max(
      0,
      form.monthlyExpense +
        (form.emergencyIncludesDebt ? debtPayment : 0) -
        illiquidIncome,
    )
  const constantTotal = form.assets.reduce(
    (sum, asset) => sum + (form.constantWeights[asset.name] ?? 0),
    0,
  )
  const growthTotal = form.growthAssets.reduce(
    (sum, name) => sum + (form.growthWeights[name] ?? 0),
    0,
  )
  const defensiveTotal = form.defensiveAssets.reduce(
    (sum, name) => sum + (form.defensiveWeights[name] ?? 0),
    0,
  )
  const firstAssetName = form.assets[0]?.name
  const calibrationStats =
    calibration && firstAssetName
      ? calibration.assets[firstAssetName]?.windows[form.calibrationWindow]
      : undefined

  return (
    <form
      className="card setup-card"
      onSubmit={(event) => {
        event.preventDefault()
        onRun()
      }}
    >
      <div className="setup-head">
        <div>
          <h2 className="card-title">假设与情景设置</h2>
          <p className="card-sub">
            修改假设后运行；每个结果都绑定一个可追溯的 run_id。
          </p>
        </div>
        <div className="form-actions inline-actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy !== null}
          >
            {busy === 'run' ? '计算中…' : '运行推演'}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy !== null || !calibration}
            onClick={onCompare}
          >
            {busy === 'compare' ? '对比中…' : '窗口对比'}
          </button>
        </div>
      </div>

      <div className="setup-grid">
        <section className="setup-panel">
          <div className="section-head">
            <h3>情景与历史校准</h3>
            <span className="section-note">历史不是预测</span>
          </div>
          <Field label="情景名称">
            <input
              type="text"
              value={form.name}
              onChange={(event) => onChange({ name: event.target.value })}
            />
          </Field>
          <Field label="校准窗口" hint="切换会立即更新资产假设">
            <select
              value={form.calibrationWindow}
              onChange={(event) => {
                const window = event.target.value
                if (calibration) {
                  onApplyCalibration(window)
                } else {
                  onChange({ calibrationWindow: window })
                }
              }}
            >
              {calibration
                ? Object.keys(calibration.correlations).map((window) => (
                    <option key={window} value={window}>
                      {calibrationLabel(calibration, window)}
                    </option>
                  ))
                : ['5y', '10y', '15y', 'full'].map((window) => (
                    <option key={window} value={window}>
                      {window}
                    </option>
                  ))}
            </select>
          </Field>
          {calibration ? (
            <>
              <div className="table-scroll">
                <table className="mini-table">
                  <thead>
                    <tr>
                      <th>资产</th>
                      <th>实际收益</th>
                      <th>波动率</th>
                      <th>样本</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calibration.asset_order.map((key) => {
                      const meta = calibration.assets[key]
                      const stats = meta?.windows[form.calibrationWindow]
                      if (!stats) return null
                      return (
                        <tr key={key}>
                          <td>{meta.label}</td>
                          <td>{(stats.real_geo * 100).toFixed(2)}%</td>
                          <td>{(stats.volatility * 100).toFixed(2)}%</td>
                          <td>
                            {stats.months} 月
                            {stats.is_short ? (
                              <span className="role-tag warning-tag">
                                历史不足
                              </span>
                            ) : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="form-note">
                {calibration.disclaimer} 所有金额为今日购买力，已按 2%
                通胀折算；数据版本 {form.dataVersion}。
              </p>
            </>
          ) : (
            <p className="form-note">
              没有找到校准快照；可以手动填写资产收益与波动率。
            </p>
          )}
        </section>

        <section className="setup-panel">
          <div className="section-head">
            <h3>家庭现金流与应急金</h3>
            <span className="section-note">应急金优先</span>
          </div>
          <div className="field-grid">
            <Field label="当前年龄">
              <NumberInput
                value={form.currentAge}
                step={0.5}
                min={0}
                suffix="岁"
                onChange={(value) => onChange({ currentAge: value })}
              />
            </Field>
            <Field label="月收入">
              <WanInput
                value={form.monthlyIncome}
                onChange={(value) => onChange({ monthlyIncome: value })}
              />
            </Field>
            <Field label="月支出">
              <WanInput
                value={form.monthlyExpense}
                onChange={(value) => onChange({ monthlyExpense: value })}
              />
            </Field>
            <Field label="收入年增长">
              <PercentInput
                value={form.incomeGrowth}
                onChange={(value) => onChange({ incomeGrowth: value })}
              />
            </Field>
            <Field label="支出年增长">
              <PercentInput
                value={form.expenseGrowth}
                onChange={(value) => onChange({ expenseGrowth: value })}
              />
            </Field>
            <Field label="应急金月数">
              <NumberInput
                value={form.emergencyMonths}
                step={1}
                min={0}
                suffix="个月"
                onChange={(value) => onChange({ emergencyMonths: value })}
              />
            </Field>
          </div>
          <div className="inline-row spaced">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.emergencyIncludesDebt}
                onChange={(event) =>
                  onChange({ emergencyIncludesDebt: event.target.checked })
                }
              />
              应急金覆盖月供
            </label>
            <Field label="事件资金顺序">
              <select
                value={form.eventWithdrawalOrder}
                onChange={(event) =>
                  onChange({
                    eventWithdrawalOrder: event.target
                      .value as FormState['eventWithdrawalOrder'],
                  })
                }
              >
                <option value="investments_first">先用投资资产</option>
                <option value="emergency_first">先用应急金</option>
              </select>
            </Field>
          </div>
          <p className="form-note">
            月结余先补足应急金，再投入金融资产；现金流缺口先用应急金。
            计划性事件会同时使用投资资产（含现金）和应急金，顺序只决定先用哪一部分；
            非流动资产不会自动卖出。
          </p>
        </section>

        <section className="setup-panel span-2">
          <div className="section-head">
            <h3>初始资产</h3>
            <span className="section-note">
              流动资产合计 {fmtMoney(liquidTotal)} · 应急金目标约{' '}
              {fmtMoney(emergencyTarget)} · 现金 {fmtMoney(cashHolding)}
            </span>
          </div>
          <div className="table-scroll">
            <table className="mini-table holdings-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th>当前市值</th>
                  <th>年增长/折旧</th>
                  <th>月租金/收入</th>
                  <th>卖出费率</th>
                  <th>卖出年龄</th>
                </tr>
              </thead>
              <tbody>
                {form.holdings.map((holding, index) => {
                  const asset = form.assets.find(
                    (item) => item.name === holding.asset,
                  )
                  return (
                    <tr key={`${holding.asset}-${index}`}>
                      <td>
                        {holding.liquidity === 'liquid' ? (
                          <span className="asset-cell">
                            <strong>{asset?.label ?? holding.label}</strong>
                            <span className="role-tag">
                              {roleLabels[asset?.role ?? 'growth']}
                            </span>
                          </span>
                        ) : (
                          <input
                            className="inline-text"
                            type="text"
                            value={holding.label}
                            aria-label="非流动资产名称"
                            onChange={(event) =>
                              onHoldingChange(index, {
                                label: event.target.value,
                              })
                            }
                          />
                        )}
                      </td>
                      <td>
                        <WanInput
                          value={holding.value}
                          onChange={(value) =>
                            onHoldingChange(index, { value })
                          }
                        />
                      </td>
                      <td>
                        {holding.liquidity === 'illiquid' ? (
                          <PercentInput
                            value={holding.growthRate}
                            onChange={(value) =>
                              onHoldingChange(index, { growthRate: value })
                            }
                          />
                        ) : (
                          <span className="muted-cell">—</span>
                        )}
                      </td>
                      <td>
                        {holding.liquidity === 'illiquid' ? (
                          <WanInput
                            value={holding.monthlyIncome}
                            onChange={(value) =>
                              onHoldingChange(index, { monthlyIncome: value })
                            }
                          />
                        ) : (
                          <span className="muted-cell">—</span>
                        )}
                      </td>
                      <td>
                        {holding.liquidity === 'illiquid' ? (
                          <PercentInput
                            value={holding.sellingCostRate}
                            onChange={(value) =>
                              onHoldingChange(index, { sellingCostRate: value })
                            }
                          />
                        ) : (
                          <span className="muted-cell">—</span>
                        )}
                      </td>
                      <td>
                        {holding.liquidity === 'illiquid' ? (
                          <NullableNumberInput
                            value={holding.sellAge}
                            step={0.5}
                            suffix="岁"
                            onChange={(value) =>
                              onHoldingChange(index, { sellAge: value })
                            }
                          />
                        ) : (
                          <span className="muted-cell">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="form-note">
            非流动资产不会自动变现；如需在推演期内卖出，填写卖出年龄，并在“负债”里关联按揭。
          </p>
        </section>

        <section className="setup-panel span-2">
          <div className="section-head">
            <h3>资产假设</h3>
            <span className="section-note">
              {calibrationLabel(calibration, form.calibrationWindow)} · 费后实际收益
            </span>
          </div>
          <div className="table-scroll">
            <table className="mini-table holdings-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th>角色</th>
                  <th>实际收益</th>
                  <th>波动率</th>
                  <th>年费率</th>
                  <th>校准来源</th>
                </tr>
              </thead>
              <tbody>
                {form.assets.map((asset, index) => {
                  const meta = calibration?.assets[asset.name]
                  const stats = meta?.windows[form.calibrationWindow]
                  return (
                    <tr key={asset.name}>
                      <td>
                        <strong>{asset.label}</strong>
                      </td>
                      <td>
                        <span className="role-tag">
                          {roleLabels[asset.role]}
                        </span>
                      </td>
                      <td>
                        <PercentInput
                          value={asset.expectedReturn}
                          onChange={(value) =>
                            onAssetChange(index, { expectedReturn: value })
                          }
                        />
                      </td>
                      <td>
                        <PercentInput
                          value={asset.volatility}
                          onChange={(value) =>
                            onAssetChange(index, { volatility: value })
                          }
                        />
                      </td>
                      <td>
                        <PercentInput
                          value={asset.expenseRatio}
                          onChange={(value) =>
                            onAssetChange(index, { expenseRatio: value })
                          }
                        />
                      </td>
                      <td className="source-cell">
                        {meta ? (
                          <>
                            <div>{meta.series_type}</div>
                            <div>
                              {stats
                                ? `${stats.start} 起 · ${stats.months} 月`
                                : '—'}
                            </div>
                            {stats?.is_short ? (
                              <span className="role-tag warning-tag">
                                历史不足
                              </span>
                            ) : null}
                          </>
                        ) : (
                          '手动假设'
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <details className="table-view">
            <summary>
              历史相关矩阵（{form.calibrationWindow}）
              {calibration?.correlations[form.calibrationWindow]?.is_short
                ? ' · 历史不足'
                : ''}
            </summary>
            {calibration?.correlations[form.calibrationWindow] ? (
              <p className="form-note">
                共同区间{' '}
                {calibration.correlations[form.calibrationWindow].start}–
                {calibration.correlations[form.calibrationWindow].end} ·{' '}
                {calibration.correlations[form.calibrationWindow].months} 月
                {calibration.correlations[form.calibrationWindow]
                  .requested_months
                  ? ` / 请求 ${
                      calibration.correlations[form.calibrationWindow]
                        .requested_months
                    } 月`
                  : '（全历史可用区间）'}
                。
              </p>
            ) : null}
            <div className="table-scroll">
              <table className="mini-table correlation-table">
                <thead>
                  <tr>
                    <th />
                    {form.assets.map((asset) => (
                      <th key={asset.name}>{asset.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {form.correlation.map((row, rowIndex) => (
                    <tr key={form.assets[rowIndex]?.name ?? rowIndex}>
                      <th>{form.assets[rowIndex]?.label ?? rowIndex}</th>
                      {row.map((value, columnIndex) => (
                        <td key={columnIndex}>{value.toFixed(2)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <p className="form-note">
            权益与债券使用官方全收益/财富指数，分红再投资；指数未扣产品费率，可在费用列补充。
            纳指100 为人民币、含汇率、未对冲；黄金为 COMEX 黄金连续（USD/oz）×
            中行 USD/CNY 折算人民币/克，含汇率、未对冲，无分红。
            {calibrationStats ? '' : ' 当前窗口没有可用的历史统计。'}
          </p>
        </section>

        <section className="setup-panel">
          <div className="section-head">
            <h3>投资策略</h3>
            <span className="section-note">目标权重</span>
          </div>
          <div className="field-grid">
            <Field label="策略类型">
              <select
                value={form.strategyKind}
                onChange={(event) =>
                  onChange({
                    strategyKind: event.target.value as FormState['strategyKind'],
                  })
                }
              >
                <option value="glide">随年龄降成长</option>
                <option value="constant">恒定比例</option>
              </select>
            </Field>
            <Field label="再平衡">
              <select
                value={form.rebalance}
                onChange={(event) =>
                  onChange({
                    rebalance: event.target.value as FormState['rebalance'],
                  })
                }
              >
                <option value="annual">年度</option>
                <option value="monthly">月度</option>
                <option value="none">不再平衡</option>
              </select>
            </Field>
          </div>

          {form.strategyKind === 'constant' ? (
            <>
              <div className="table-scroll">
                <table className="mini-table">
                  <thead>
                    <tr>
                      <th>资产</th>
                      <th>目标权重</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.assets.map((asset) => (
                      <tr key={asset.name}>
                        <td>{asset.label}</td>
                        <td>
                          <PercentInput
                            value={form.constantWeights[asset.name] ?? 0}
                            onChange={(value) =>
                              onChange({
                                constantWeights: {
                                  ...form.constantWeights,
                                  [asset.name]: value,
                                },
                              })
                            }
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p
                className={
                  Math.abs(constantTotal - 1) > 1e-6
                    ? 'form-note danger'
                    : 'form-note'
                }
              >
                合计 {(constantTotal * 100).toFixed(1)}%，必须为 100%。
              </p>
            </>
          ) : (
            <>
              <div className="strategy-group">
                <div className="strategy-group-head">
                  <strong>成长组</strong>
                  <span>合计 {(growthTotal * 100).toFixed(0)}%</span>
                </div>
                <div className="weight-grid">
                  {form.growthAssets.map((name) => {
                    const asset = form.assets.find((item) => item.name === name)
                    return (
                      <Field key={name} label={asset?.label ?? name}>
                        <PercentInput
                          value={form.growthWeights[name] ?? 0}
                          onChange={(value) =>
                            onChange({
                              growthWeights: {
                                ...form.growthWeights,
                                [name]: value,
                              },
                            })
                          }
                        />
                      </Field>
                    )
                  })}
                </div>
              </div>
              <div className="strategy-group">
                <div className="strategy-group-head">
                  <strong>防御组</strong>
                  <span>合计 {(defensiveTotal * 100).toFixed(0)}%</span>
                </div>
                <div className="weight-grid">
                  {form.defensiveAssets.map((name) => {
                    const asset = form.assets.find((item) => item.name === name)
                    return (
                      <Field key={name} label={asset?.label ?? name}>
                        <PercentInput
                          value={form.defensiveWeights[name] ?? 0}
                          onChange={(value) =>
                            onChange({
                              defensiveWeights: {
                                ...form.defensiveWeights,
                                [name]: value,
                              },
                            })
                          }
                        />
                      </Field>
                    )
                  })}
                </div>
              </div>
              <div className="field-grid">
                <Field label="期初成长权重">
                  <PercentInput
                    value={form.growthStart}
                    onChange={(value) => onChange({ growthStart: value })}
                  />
                </Field>
                <Field label="期末成长权重">
                  <PercentInput
                    value={form.growthEnd}
                    onChange={(value) => onChange({ growthEnd: value })}
                  />
                </Field>
                <Field label="开始年龄">
                  <NumberInput
                    value={form.glideStartAge}
                    step={1}
                    min={0}
                    suffix="岁"
                    onChange={(value) => onChange({ glideStartAge: value })}
                  />
                </Field>
                <Field label="结束年龄">
                  <NumberInput
                    value={form.glideEndAge}
                    step={1}
                    min={0}
                    suffix="岁"
                    onChange={(value) => onChange({ glideEndAge: value })}
                  />
                </Field>
                <Field label="成长下限">
                  <PercentInput
                    value={form.floor}
                    onChange={(value) => onChange({ floor: value })}
                  />
                </Field>
                <Field label="成长上限">
                  <PercentInput
                    value={form.cap}
                    onChange={(value) => onChange({ cap: value })}
                  />
                </Field>
              </div>
              <p className="form-note">
                成长组总权重按年龄线性变化；组内比例固定，防御组与现金补足剩余仓位。
              </p>
            </>
          )}
        </section>

        <section className="setup-panel">
          <div className="section-head">
            <h3>负债</h3>
            <span className="section-note">按揭从初始资产中扣减</span>
          </div>
          <div className="table-scroll">
            <table className="mini-table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>余额</th>
                  <th>年利率</th>
                  <th>剩余月数</th>
                  <th>关联资产</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {form.liabilities.map((liability, index) => (
                  <tr key={`${liability.name}-${index}`}>
                    <td>
                      <input
                        className="inline-text"
                        type="text"
                        value={liability.name}
                        aria-label="负债名称"
                        onChange={(event) =>
                          onLiabilityChange(index, {
                            name: event.target.value,
                          })
                        }
                      />
                    </td>
                    <td>
                      <WanInput
                        value={liability.balance}
                        onChange={(value) =>
                          onLiabilityChange(index, { balance: value })
                        }
                      />
                    </td>
                    <td>
                      <PercentInput
                        value={liability.annualRate}
                        onChange={(value) =>
                          onLiabilityChange(index, { annualRate: value })
                        }
                      />
                    </td>
                    <td>
                      <NumberInput
                        value={liability.remainingMonths}
                        step={12}
                        min={1}
                        suffix="月"
                        onChange={(value) =>
                          onLiabilityChange(index, {
                            remainingMonths: value,
                          })
                        }
                      />
                    </td>
                    <td>
                      <select
                        value={liability.linkedHolding ?? ''}
                        onChange={(event) =>
                          onLiabilityChange(index, {
                            linkedHolding: event.target.value || null,
                          })
                        }
                      >
                        <option value="">不关联</option>
                        {form.holdings
                          .filter((holding) => holding.liquidity === 'illiquid')
                          .map((holding) => (
                            <option
                              key={`${holding.asset}-${holding.label}`}
                              value={holding.label}
                            >
                              {holding.label}
                            </option>
                          ))}
                      </select>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label="删除负债"
                        onClick={() => onRemoveLiability(index)}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className="add-btn" onClick={onAddLiability}>
            + 添加负债
          </button>
          <p className="form-note">
            月供按等额本息自动计算；卖出关联资产时，剩余本金从卖出款中偿还。
          </p>
        </section>

        <section className="setup-panel span-2">
          <div className="section-head">
            <h3>人生事件</h3>
            <span className="section-note">持续收支、按揭、买入与卖出</span>
          </div>
          {form.events.map((event, index) => (
            <EventCard
              key={event.id}
              event={event}
              index={index}
              form={form}
              onEventChange={onEventChange}
              onPurchaseChange={onPurchaseChange}
              onRemoveEvent={onRemoveEvent}
            />
          ))}
          <div className="add-row">
            <button
              type="button"
              className="add-btn"
              onClick={() => onAddEvent('one_off')}
            >
              + 一次性支出
            </button>
            <button
              type="button"
              className="add-btn"
              onClick={() => onAddEvent('recurring_income')}
            >
              + 持续收入
            </button>
            <button
              type="button"
              className="add-btn"
              onClick={() => onAddEvent('recurring_expense')}
            >
              + 持续支出
            </button>
            <button
              type="button"
              className="add-btn"
              onClick={() => onAddEvent('purchase')}
            >
              + 买房/买车
            </button>
          </div>
        </section>

        <section className="setup-panel span-2">
          <div className="section-head">
            <h3>人生道路对比</h3>
            <span className="section-note">
              同 seed / 路径数 / 资产假设，只改事件
            </span>
          </div>
          <p className="form-note">
            基准路径“{form.name || '当前路径'}”包含当前全部 {form.events.length}{' '}
            个事件。下面每条对比路径勾选它包含的事件；所有路径共用同一随机种子和路径数。
          </p>
          {form.pathVariants.map((variant, index) => (
            <div className="path-card" key={variant.id}>
              <div className="path-head">
                <Field label="路径名称">
                  <input
                    type="text"
                    value={variant.name}
                    onChange={(event) =>
                      onPathVariantChange(index, { name: event.target.value })
                    }
                  />
                </Field>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="删除对比路径"
                  onClick={() => onRemovePathVariant(index)}
                >
                  ×
                </button>
              </div>
              <div className="path-events">
                {form.events.map((event) => (
                  <label className="checkbox" key={event.id}>
                    <input
                      type="checkbox"
                      checked={variant.includedEventIds.includes(event.id)}
                      onChange={(changeEvent) => {
                        const included = changeEvent.target.checked
                          ? [...variant.includedEventIds, event.id]
                          : variant.includedEventIds.filter(
                              (id) => id !== event.id,
                            )
                        onPathVariantChange(index, {
                          includedEventIds: included,
                        })
                      }}
                    />
                    {event.name}
                  </label>
                ))}
                {form.events.length === 0 ? (
                  <span className="form-note">先在“人生事件”里添加事件。</span>
                ) : null}
              </div>
            </div>
          ))}
          <div className="add-row two">
            <button
              type="button"
              className="add-btn"
              disabled={form.pathVariants.length >= 4}
              onClick={onAddPathVariant}
            >
              + 添加对比路径
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy !== null || form.pathVariants.length === 0}
              onClick={onRunPathCompare}
            >
              {busy === 'compare' ? '对比中…' : '运行道路对比'}
            </button>
          </div>
          <p className="form-note">
            最多 4 条对比路径；基准路径始终包含当前全部事件。差异是条件对比，不是因果推断。
          </p>
        </section>

        <section className="setup-panel span-2">
          <div className="section-head">
            <h3>模拟设置</h3>
            <span className="section-note">固定种子可复现</span>
          </div>
          <div className="field-grid four">
            <Field
              label="推演年限"
              hint="未来多少年，按月推演"
            >
              <NumberInput
                value={form.horizonYears}
                step={1}
                min={1}
                max={50}
                suffix="年"
                onChange={(value) => onChange({ horizonYears: value })}
              />
            </Field>
            <Field
              label="路径数"
              hint="越多分位数越稳；误差约按 1/√N 缩小。快速试算用 500–1,000。"
            >
              <NumberInput
                value={form.nPaths}
                step={1000}
                min={100}
                max={100000}
                onChange={(value) => onChange({ nPaths: value })}
              />
            </Field>
            <Field
              label="随机种子"
              hint="相同种子 + 相同假设 = 完全相同结果；对比时保持不变。"
            >
              <NumberInput
                value={form.seed}
                step={1}
                min={0}
                onChange={(value) => onChange({ seed: value })}
              />
            </Field>
            <label className="checkbox self-end">
              <input
                type="checkbox"
                checked={form.includeExplanation}
                onChange={(event) =>
                  onChange({ includeExplanation: event.target.checked })
                }
              />
              AI 解释
            </label>
          </div>
          <p className="form-note">
            运行会写入 SQLite 并导出内容哈希快照；图表、解释和参数快照共用同一个 run_id。
          </p>
        </section>
      </div>

      <div className="form-actions bottom-actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy !== null}
        >
          {busy === 'run' ? '计算中…' : '运行推演'}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy !== null || !calibration}
          onClick={onCompare}
        >
          {busy === 'compare' ? '对比中…' : '近 5/10/15 年窗口对比'}
        </button>
      </div>
      <Glossary />
    </form>
  )
}
