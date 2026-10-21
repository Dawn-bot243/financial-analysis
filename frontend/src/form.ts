import type {
  AssetAssumption,
  AssetRole,
  CalibrationSnapshot,
  InitialHolding,
  Liability,
  LifeEvent,
  Rebalance,
  ScenarioRequest,
  StrategySpec,
  WithdrawalOrder,
} from './types'

export type EventKind =
  | 'one_off'
  | 'recurring_income'
  | 'recurring_expense'
  | 'purchase'

export interface AssetForm {
  name: string
  label: string
  role: AssetRole
  expectedReturn: number
  volatility: number
  expenseRatio: number
}

export interface HoldingForm {
  asset: string
  label: string
  value: number
  liquidity: 'liquid' | 'illiquid'
  growthRate: number
  monthlyIncome: number
  sellingCostRate: number
  sellAge: number | null
  liabilityName: string | null
}

export interface LiabilityForm {
  name: string
  balance: number
  annualRate: number
  remainingMonths: number
  linkedHolding: string | null
}

export interface PurchaseForm {
  asset: string
  label: string
  price: number
  downPayment: number
  loanRate: number
  loanMonths: number
  appreciationRate: number
  monthlyRent: number
  sellingCostRate: number
  sellAge: number | null
}

export interface EventForm {
  id: string
  kind: EventKind
  name: string
  startAge: number
  endAge: number | null
  // Approximate timing window in years. 0 means the exact start month.
  windowYears: number
  oneOffExpense: number
  monthlyIncome: number
  monthlyExpense: number
  purchase: PurchaseForm | null
}

export interface PathVariant {
  id: string
  name: string
  includedEventIds: string[]
}

export interface FormState {
  name: string
  currentAge: number
  monthlyIncome: number
  monthlyExpense: number
  incomeGrowth: number
  expenseGrowth: number
  emergencyMonths: number
  emergencyIncludesDebt: boolean
  eventWithdrawalOrder: WithdrawalOrder

  holdings: HoldingForm[]
  liabilities: LiabilityForm[]
  assets: AssetForm[]
  correlation: number[][]
  dataVersion: string
  calibrationWindow: string

  strategyKind: 'constant' | 'glide'
  constantWeights: Record<string, number>
  growthAssets: string[]
  growthWeights: Record<string, number>
  defensiveAssets: string[]
  defensiveWeights: Record<string, number>
  cashAsset: string
  cashWeight: number
  growthStart: number
  growthEnd: number
  glideStartAge: number
  glideEndAge: number
  floor: number
  cap: number
  rebalance: Rebalance

  events: EventForm[]
  pathVariants: PathVariant[]
  horizonYears: number
  nPaths: number
  seed: number
  includeExplanation: boolean
}

export function equalWeights(names: string[]): Record<string, number> {
  const result: Record<string, number> = {}
  if (names.length === 0) return result
  const weight = 1 / names.length
  for (const name of names) result[name] = weight
  return result
}

export function defaultConstantWeights(assets: AssetForm[]): Record<string, number> {
  const growth = assets.filter((asset) => asset.role === 'growth').map((a) => a.name)
  const defensive = assets
    .filter((asset) => asset.role === 'defensive')
    .map((a) => a.name)
  const cash = assets.filter((asset) => asset.role === 'cash').map((a) => a.name)
  const growthWeight = 0.6 + (defensive.length ? 0 : 0.3) + (cash.length ? 0 : 0.1)
  const defensiveWeight = defensive.length ? 0.3 : 0
  const cashWeight = cash.length ? 0.1 : 0
  const result: Record<string, number> = {}
  for (const name of growth) result[name] = growthWeight / growth.length
  for (const name of defensive) result[name] = defensiveWeight / defensive.length
  for (const name of cash) result[name] = cashWeight / cash.length
  return result
}

function defaultHolding(
  asset: string,
  label: string,
  liquidity: 'liquid' | 'illiquid',
): HoldingForm {
  return {
    asset,
    label,
    value: 0,
    liquidity,
    growthRate: liquidity === 'illiquid' ? 0.02 : 0,
    monthlyIncome: 0,
    sellingCostRate: liquidity === 'illiquid' ? 0.02 : 0,
    sellAge: null,
    liabilityName: null,
  }
}

function eventFromRequest(event: LifeEvent, index: number): EventForm {
  const startAge = event.start_age ?? event.age ?? 30
  if (event.purchase) {
    return {
      id: `event-${index}`,
      kind: 'purchase',
      name: event.name,
      startAge,
      endAge: event.end_age ?? null,
      windowYears: event.window_years ?? 0,
      oneOffExpense: event.one_off_expense ?? event.amount ?? 0,
      monthlyIncome: event.monthly_income ?? 0,
      monthlyExpense: event.monthly_expense ?? 0,
      purchase: {
        asset: event.purchase.asset,
        label: event.purchase.label,
        price: event.purchase.price,
        downPayment: event.purchase.down_payment,
        loanRate: event.purchase.loan_annual_rate,
        loanMonths: event.purchase.loan_months,
        appreciationRate: event.purchase.appreciation_rate,
        monthlyRent: event.purchase.monthly_rent,
        sellingCostRate: event.purchase.selling_cost_rate,
        sellAge: event.purchase.sell_age ?? null,
      },
    }
  }
  const kind: EventKind =
    (event.one_off_expense ?? event.amount ?? 0) > 0
      ? 'one_off'
      : (event.monthly_income ?? 0) > 0
        ? 'recurring_income'
        : 'recurring_expense'
  return {
    id: `event-${index}`,
    kind,
    name: event.name,
    startAge,
    endAge: event.end_age ?? null,
    windowYears: event.window_years ?? 0,
    oneOffExpense: event.one_off_expense ?? event.amount ?? 0,
    monthlyIncome: event.monthly_income ?? 0,
    monthlyExpense: event.monthly_expense ?? 0,
    purchase: null,
  }
}

export function formFromRequest(request: ScenarioRequest): FormState {
  const marketAssets: AssetForm[] = request.market.assets.map((asset) => ({
    name: asset.name,
    label: asset.label || asset.name,
    role: asset.role ?? 'growth',
    expectedReturn: asset.expected_real_return,
    volatility: asset.volatility,
    expenseRatio: asset.expense_ratio,
  }))
  const marketNames = new Set(marketAssets.map((asset) => asset.name))
  const holdings: HoldingForm[] = []

  for (const asset of marketAssets) {
    const existing = request.household.holdings.find(
      (holding) => holding.asset === asset.name && holding.liquidity === 'liquid',
    )
    holdings.push(
      existing
        ? {
            asset: existing.asset,
            label: existing.label || asset.label,
            value: existing.value,
            liquidity: 'liquid',
            growthRate: 0,
            monthlyIncome: 0,
            sellingCostRate: 0,
            sellAge: null,
            liabilityName: null,
          }
        : defaultHolding(asset.name, asset.label, 'liquid'),
    )
  }

  const realEstate = request.household.holdings.find(
    (holding) =>
      holding.asset === 'real_estate' ||
      (holding.liquidity === 'illiquid' && !marketNames.has(holding.asset)),
  )
  holdings.push(
    realEstate
      ? {
          asset: realEstate.asset,
          label: realEstate.label || '房产',
          value: realEstate.value,
          liquidity: 'illiquid',
          growthRate: realEstate.growth_rate,
          monthlyIncome: realEstate.monthly_income,
          sellingCostRate: realEstate.selling_cost_rate,
          sellAge: realEstate.sell_age,
          liabilityName: realEstate.liability_name,
        }
      : defaultHolding('real_estate', '房产', 'illiquid'),
  )
  const other = request.household.holdings.find(
    (holding) => holding.asset === 'other_illiquid',
  )
  holdings.push(
    other
      ? {
          asset: other.asset,
          label: other.label || '其他不动产',
          value: other.value,
          liquidity: 'illiquid',
          growthRate: other.growth_rate,
          monthlyIncome: other.monthly_income,
          sellingCostRate: other.selling_cost_rate,
          sellAge: other.sell_age,
          liabilityName: other.liability_name,
        }
      : defaultHolding('other_illiquid', '其他不动产', 'illiquid'),
  )

  const growthAssets = request.strategy.growth_assets.length
    ? request.strategy.growth_assets
    : marketAssets.filter((asset) => asset.role === 'growth').map((a) => a.name)
  const defensiveAssets = request.strategy.defensive_assets.length
    ? request.strategy.defensive_assets
    : marketAssets.filter((asset) => asset.role === 'defensive').map((a) => a.name)
  const cashAsset =
    request.strategy.cash_asset ||
    marketAssets.find((asset) => asset.role === 'cash')?.name ||
    'cash'

  return {
    name: request.name,
    currentAge: request.household.current_age,
    monthlyIncome: request.household.monthly_income,
    monthlyExpense: request.household.monthly_expense,
    incomeGrowth: request.household.income_growth_real,
    expenseGrowth: request.household.expense_growth_real,
    emergencyMonths: request.household.emergency_fund_months ?? 10,
    emergencyIncludesDebt: request.household.emergency_fund_includes_debt ?? true,
    eventWithdrawalOrder:
      request.household.event_withdrawal_order ?? 'investments_first',

    holdings,
    liabilities: request.household.liabilities.map((liability) => ({
      name: liability.name,
      balance: liability.balance,
      annualRate: liability.annual_rate,
      remainingMonths: liability.remaining_months,
      linkedHolding: liability.linked_holding ?? null,
    })),
    assets: marketAssets,
    correlation: request.market.correlation.map((row) => [...row]),
    dataVersion: request.data_version ?? 'none',
    calibrationWindow: request.calibration_window ?? '10y',

    strategyKind: request.strategy.kind === 'constant' ? 'constant' : 'glide',
    constantWeights:
      request.strategy.weights ??
      defaultConstantWeights(marketAssets),
    growthAssets,
    growthWeights:
      Object.keys(request.strategy.growth_weights ?? {}).length
        ? { ...request.strategy.growth_weights }
        : equalWeights(growthAssets),
    defensiveAssets,
    defensiveWeights:
      Object.keys(request.strategy.defensive_weights ?? {}).length
        ? { ...request.strategy.defensive_weights }
        : equalWeights(defensiveAssets),
    cashAsset,
    cashWeight: request.strategy.cash_weight ?? 0,
    growthStart: request.strategy.growth_start ?? 0.8,
    growthEnd: request.strategy.growth_end ?? 0.4,
    glideStartAge: request.strategy.glide_start_age ?? 30,
    glideEndAge: request.strategy.glide_end_age ?? 60,
    floor: request.strategy.floor ?? 0,
    cap: request.strategy.cap ?? 1,
    rebalance: request.strategy.rebalance ?? 'annual',

    events: request.household.events.map((event, index) =>
      eventFromRequest(event, index),
    ),
    pathVariants: [],
    horizonYears: request.horizon_years,
    nPaths: request.n_paths,
    seed: request.seed,
    includeExplanation: request.include_explanation,
  }
}

export function requestFromForm(form: FormState): ScenarioRequest {
  const assets: AssetAssumption[] = form.assets.map((asset) => ({
    name: asset.name,
    label: asset.label,
    role: asset.role,
    expected_real_return: asset.expectedReturn,
    volatility: asset.volatility,
    expense_ratio: asset.expenseRatio,
    liquid: true,
  }))

  const holdings: InitialHolding[] = form.holdings.map((holding) => ({
    asset: holding.asset,
    label: holding.label,
    value: holding.value,
    liquidity: holding.liquidity,
    growth_rate: holding.growthRate,
    monthly_income: holding.monthlyIncome,
    selling_cost_rate: holding.sellingCostRate,
    sell_age: holding.sellAge,
    // Linking is done from the liability side (linked_holding) so renaming a
    // liability does not leave a stale name on the asset.
    liability_name: null,
  }))

  const liabilities: Liability[] = form.liabilities.map((liability) => ({
    name: liability.name,
    balance: liability.balance,
    annual_rate: liability.annualRate,
    remaining_months: liability.remainingMonths,
    linked_holding: liability.linkedHolding,
  }))

  const events: LifeEvent[] = form.events.map((event) => {
    const base = {
      name: event.name,
      start_age: event.startAge,
      end_age: event.endAge,
      window_years:
        event.kind === 'purchase' || event.kind === 'one_off'
          ? event.windowYears
          : 0,
      one_off_expense: event.oneOffExpense,
      monthly_income: event.monthlyIncome,
      monthly_expense: event.monthlyExpense,
      purchase: null,
    }
    if (event.kind === 'purchase' && event.purchase) {
      return {
        ...base,
        purchase: {
          asset: event.purchase.asset,
          label: event.purchase.label,
          price: event.purchase.price,
          down_payment: event.purchase.downPayment,
          loan_annual_rate: event.purchase.loanRate,
          loan_months: event.purchase.loanMonths,
          appreciation_rate: event.purchase.appreciationRate,
          monthly_rent: event.purchase.monthlyRent,
          selling_cost_rate: event.purchase.sellingCostRate,
          sell_age: event.purchase.sellAge,
        },
      }
    }
    return base
  })

  const strategy: StrategySpec = {
    kind: form.strategyKind,
    weights:
      form.strategyKind === 'constant'
        ? Object.fromEntries(
            form.assets.map((asset) => [
              asset.name,
              form.constantWeights[asset.name] ?? 0,
            ]),
          )
        : null,
    growth_assets: form.growthAssets,
    growth_weights: form.growthWeights,
    defensive_assets: form.defensiveAssets,
    defensive_weights: form.defensiveWeights,
    cash_asset: form.cashAsset,
    cash_weight: form.cashWeight,
    growth_start: form.growthStart,
    growth_end: form.growthEnd,
    glide_start_age: form.glideStartAge,
    glide_end_age: form.glideEndAge,
    floor: form.floor,
    cap: form.cap,
    rebalance: form.rebalance,
    equity_asset: form.growthAssets[0] ?? 'csi300',
    bond_asset: form.defensiveAssets[0] ?? 'bond',
  }

  return {
    name: form.name,
    market: {
      assets,
      correlation: form.correlation,
      student_t_df: 5,
    },
    household: {
      current_age: form.currentAge,
      initial_capital: 0,
      holdings,
      monthly_income: form.monthlyIncome,
      monthly_expense: form.monthlyExpense,
      income_growth_real: form.incomeGrowth,
      expense_growth_real: form.expenseGrowth,
      liabilities,
      events,
      emergency_fund_months: form.emergencyMonths,
      emergency_fund_includes_debt: form.emergencyIncludesDebt,
      event_withdrawal_order: form.eventWithdrawalOrder,
    },
    strategy,
    horizon_years: form.horizonYears,
    n_paths: form.nPaths,
    seed: form.seed,
    include_explanation: form.includeExplanation,
    data_version: form.dataVersion,
    calibration_window: form.calibrationWindow,
  }
}

export function validateForm(form: FormState): string | null {
  const assetNames = form.assets.map((asset) => asset.name)
  if (form.strategyKind === 'constant') {
    const total = assetNames.reduce(
      (sum, name) => sum + (form.constantWeights[name] ?? 0),
      0,
    )
    if (Math.abs(total - 1) > 1e-6) {
      return `恒定比例策略的资产权重之和必须为 100%，当前为 ${(total * 100).toFixed(1)}%。`
    }
  } else {
    const growthTotal = form.growthAssets.reduce(
      (sum, name) => sum + (form.growthWeights[name] ?? 0),
      0,
    )
    const defensiveTotal = form.defensiveAssets.reduce(
      (sum, name) => sum + (form.defensiveWeights[name] ?? 0),
      0,
    )
    if (growthTotal <= 0) return '成长组权重必须为正。'
    if (form.defensiveAssets.length > 0 && defensiveTotal <= 0) {
      return '防御组权重必须为正。'
    }
    if (form.glideEndAge <= form.glideStartAge) {
      return '降权益的结束年龄必须大于开始年龄。'
    }
    if (form.floor > form.cap) return '权益权重下限不能大于上限。'
  }
  for (const event of form.events) {
    if (event.windowYears < 0) {
      return `事件“${event.name}”的时间窗不能为负数。`
    }
    if (event.kind === 'purchase' && event.purchase) {
      const purchase = event.purchase
      const latest = event.startAge + event.windowYears
      if (purchase.downPayment > purchase.price + 1e-6) {
        return `事件“${event.name}”的首付不能超过总价。`
      }
      if (
        purchase.loanMonths === 0 &&
        purchase.downPayment + 1e-6 < purchase.price
      ) {
        return `事件“${event.name}”有贷款余额但贷款期数为 0。`
      }
      if (purchase.sellAge !== null && purchase.sellAge <= latest) {
        return `事件“${event.name}”的卖出年龄必须晚于时间窗结束年龄（${latest.toFixed(1)}岁）。`
      }
    }
    if (
      event.kind === 'one_off' &&
      event.windowYears > 0 &&
      event.oneOffExpense <= 0
    ) {
      return `事件“${event.name}”设置时间窗时，一次性支出必须大于 0。`
    }
    if (event.endAge !== null && event.endAge < event.startAge) {
      return `事件“${event.name}”的结束年龄不能早于开始年龄。`
    }
  }
  if (form.nPaths < 100) return '路径数至少为 100。'
  return null
}

export function calibrationAssets(
  calibration: CalibrationSnapshot,
  window: string,
): AssetForm[] {
  return calibration.asset_order.map((key) => {
    const meta = calibration.assets[key]
    const stats = meta.windows[window]
    return {
      name: key,
      label: meta.label,
      role: meta.role,
      expectedReturn: stats.real_geo,
      volatility: stats.volatility,
      expenseRatio: meta.expense_ratio,
    }
  })
}

export function newPurchase(asset: string, startAge: number): PurchaseForm {
  if (asset === 'car') {
    return {
      asset: 'car',
      label: '家用车',
      price: 250_000,
      downPayment: 100_000,
      loanRate: 0.04,
      loanMonths: 60,
      appreciationRate: -0.1,
      monthlyRent: 0,
      sellingCostRate: 0.05,
      sellAge: startAge + 5,
    }
  }
  if (asset === 'other_illiquid') {
    return {
      asset: 'other_illiquid',
      label: '其他资产',
      price: 500_000,
      downPayment: 200_000,
      loanRate: 0.035,
      loanMonths: 120,
      appreciationRate: 0.02,
      monthlyRent: 1_000,
      sellingCostRate: 0.02,
      sellAge: startAge + 10,
    }
  }
  return {
    asset: 'real_estate',
    label: '房产',
    price: 2_000_000,
    downPayment: 600_000,
    loanRate: 0.035,
    loanMonths: 300,
    appreciationRate: 0.02,
    monthlyRent: 3_000,
    sellingCostRate: 0.02,
    sellAge: startAge + 10,
  }
}

export function calibrationLabel(
  calibration: CalibrationSnapshot | null,
  window: string,
): string {
  if (!calibration) return window
  return (
    {
      '5y': '近 5 年',
      '10y': '近 10 年',
      '15y': '近 15 年',
      full: '全历史',
    }[window] ?? window
  )
}
