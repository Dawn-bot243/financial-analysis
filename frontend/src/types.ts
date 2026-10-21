export type StrategyKind = 'constant' | 'glide' | 'all_equity'
export type Rebalance = 'monthly' | 'annual' | 'none'
export type AssetRole = 'growth' | 'defensive' | 'cash' | 'illiquid'
export type Liquidity = 'liquid' | 'illiquid'
export type WithdrawalOrder = 'investments_first' | 'emergency_first'

export interface AssetAssumption {
  name: string
  label: string
  role: AssetRole
  expected_real_return: number
  volatility: number
  expense_ratio: number
  liquid: boolean
}

export interface MarketAssumptions {
  assets: AssetAssumption[]
  correlation: number[][]
  student_t_df: number
}

export interface Liability {
  name: string
  balance: number
  annual_rate: number
  remaining_months: number
  linked_holding?: string | null
}

export interface InitialHolding {
  asset: string
  label: string
  value: number
  liquidity: Liquidity
  growth_rate: number
  monthly_income: number
  selling_cost_rate: number
  sell_age: number | null
  liability_name: string | null
}

export interface AssetPurchase {
  asset: string
  label: string
  price: number
  down_payment: number
  loan_annual_rate: number
  loan_months: number
  appreciation_rate: number
  monthly_rent: number
  selling_cost_rate: number
  sell_age: number | null
}

export interface LifeEvent {
  name: string
  start_age?: number | null
  end_age?: number | null
  window_years?: number
  one_off_expense: number
  monthly_income: number
  monthly_expense: number
  purchase: AssetPurchase | null
  // legacy fields from the first MVP
  age?: number | null
  amount?: number | null
  mandatory?: boolean
}

export interface Household {
  current_age: number
  initial_capital: number
  holdings: InitialHolding[]
  monthly_income: number
  monthly_expense: number
  income_growth_real: number
  expense_growth_real: number
  liabilities: Liability[]
  events: LifeEvent[]
  emergency_fund_months: number
  emergency_fund_includes_debt: boolean
  event_withdrawal_order: WithdrawalOrder
}

export interface StrategySpec {
  kind: StrategyKind
  weights: Record<string, number> | null
  growth_assets: string[]
  growth_weights: Record<string, number>
  defensive_assets: string[]
  defensive_weights: Record<string, number>
  cash_asset: string
  cash_weight: number
  growth_start: number
  growth_end: number
  glide_start_age: number
  glide_end_age: number
  floor: number
  cap: number
  rebalance: Rebalance
  // legacy
  equity_start?: number | null
  equity_end?: number | null
  equity_asset: string
  bond_asset: string
}

export interface ScenarioRequest {
  name: string
  market: MarketAssumptions
  household: Household
  strategy: StrategySpec
  horizon_years: number
  n_paths: number
  seed: number
  include_explanation: boolean
  data_version: string
  calibration_window: string | null
  goal_amount?: number
}

export interface SimpleRequest {
  name: string
  initial_capital: number
  monthly_contribution: number
  horizon_years: number
  weights: Record<string, number>
  goal_amount: number
  calibration_window: string
  n_paths: number
  seed: number
}

export type HistoryMode = 'single' | 'portfolio'
export type HistoryRebalance = 'annual' | 'none'

export interface HistoryRequest {
  mode: HistoryMode
  asset: string
  weights: Record<string, number>
  initial_capital: number
  monthly_contribution: number
  start_date: string | null
  end_date: string | null
  lookback_years: number | null
  rebalance: HistoryRebalance
}

export interface HistoryPoint {
  date: string
  value: number
  invested: number
}

export interface HistoryAssetValue {
  asset: string
  label: string
  value: number
  weight: number
}

export interface HistoryResponse {
  run_id: string
  created_at: string
  request: HistoryRequest
  data_version: string
  code_version: string
  code_fingerprint: string
  requested_start_date: string
  requested_end_date: string
  effective_start_date: string
  effective_end_date: string
  months: number
  contribution_count: number
  initial_capital: number
  monthly_contribution: number
  total_invested: number
  terminal_value: number
  profit: number
  return_on_invested: number
  irr_annual: number | null
  max_drawdown: number
  drawdown_peak_date: string | null
  drawdown_trough_date: string | null
  path: HistoryPoint[]
  yearly: HistoryPoint[]
  final_composition: HistoryAssetValue[]
  warnings: string[]
}

export interface HistoryAssetMeta {
  name: string
  label: string
  source: string
  start: string
  end: string
}

export interface HistoryMetaResponse {
  data_version: string
  inflation_assumption: number
  latest_date: string
  assets: HistoryAssetMeta[]
  disclaimer: string
}

export interface PercentilePoint {
  p5: number
  p25: number
  p50: number
  p75: number
  p95: number
}

export interface PercentileBand {
  p5: number[]
  p25: number[]
  p50: number[]
  p75: number[]
  p95: number[]
}

export interface DrawdownSummary {
  p5: number
  p25: number
  p50: number
  p75: number
  p95: number
  hist_edges: number[]
  hist_counts: number[]
}

export interface TimingPoint {
  age: number
  probability: number
}

export interface EventResult {
  name: string
  age: number
  amount: number
  month: number
  success_probability: number
  success_ci95_low: number
  success_ci95_high: number
  mean_gap: number
  p50_gap: number
  event_type: 'cashflow' | 'purchase'
  has_goal: boolean
  window_years?: number
  window_start_age?: number | null
  window_end_age?: number | null
  natural_success_probability?: number | null
  deadline_success_probability?: number | null
  failure_probability?: number | null
  median_action_age?: number | null
  action_age_p25?: number | null
  action_age_p75?: number | null
  median_cost?: number | null
  funding_investable_mean?: number | null
  funding_emergency_mean?: number | null
  funding_emergency_share_mean?: number | null
  timing?: TimingPoint[]
}

export interface CompositionItem {
  label: string
  value: number
  kind: 'investable' | 'emergency' | 'illiquid' | 'liability'
}

export interface RunMetrics {
  months: number[]
  years: number[]
  assets: PercentileBand
  net_worth: PercentileBand
  terminal_assets: PercentilePoint
  terminal_net_worth: PercentilePoint
  max_drawdown: DrawdownSummary
  annualized_twr: PercentilePoint
  events: EventResult[]
  joint_shortfall_probability: number
  joint_shortfall_ci95_low: number
  joint_shortfall_ci95_high: number
  ruin_probability: number
  ruin_ci95_low: number
  ruin_ci95_high: number
  total_contributions: number
  total_event_withdrawals: number
  total_debt_interest: number
  initial_capital: number
  monthly_surplus: number
  monthly_debt_payment: number
  goal_amount?: number
  goal_probability?: number
  goal_ci95_low?: number
  goal_ci95_high?: number
  emergency_fund?: PercentileBand | null
  illiquid_assets?: PercentileBand | null
  liabilities?: PercentileBand | null
  terminal_emergency_fund?: PercentilePoint | null
  terminal_illiquid_assets?: PercentilePoint | null
  terminal_liabilities?: PercentilePoint | null
  terminal_composition: CompositionItem[]
  emergency_fund_target_months: number
  initial_net_worth?: number | null
  initial_emergency_fund?: number | null
  initial_illiquid_assets?: number | null
  initial_liabilities?: number | null
}

export interface Explanation {
  summary: string
  bullets: string[]
  caveats: string[]
  metric_refs: string[]
  source: 'template' | 'llm'
  model: string | null
  warnings: string[]
  templates: Record<string, unknown> | null
}

export interface RunResponse {
  run_id: string
  created_at: string
  request: ScenarioRequest
  metrics: RunMetrics
  explanation: Explanation
  warnings: string[]
  code_version: string
  code_fingerprint: string
  data_version: string
}

export interface CompareItem {
  run_id: string
  name: string
  terminal_assets_p50: number
  terminal_net_worth_p50: number
  max_drawdown_p50: number
  joint_shortfall_probability: number
  ruin_probability: number
  terminal_assets_p5?: number | null
  terminal_assets_p25?: number | null
  terminal_assets_p75?: number | null
  terminal_assets_p95?: number | null
  terminal_emergency_p50?: number | null
  terminal_illiquid_p50?: number | null
  terminal_liabilities_p50?: number | null
  total_contributions?: number
  total_event_withdrawals?: number
}

export interface CompareResponse {
  items: CompareItem[]
}

export interface RunListItem {
  run_id: string
  created_at: string
  name: string
  terminal_assets_p50: number
  joint_shortfall_probability: number
}

export interface ScenarioPreset {
  name: string
  equity: number
  bond: number
  cash: number
}

export interface CalibrationWindowStats {
  start: string
  end: string
  months: number
  requested_months?: number | null
  is_short?: boolean
  nominal_geo: number
  real_geo: number
  volatility: number
}

export interface CalibrationAsset {
  label: string
  role: AssetRole
  series_type: string
  source: string
  fee_included: boolean
  expense_ratio: number
  note: string
  windows: Record<string, CalibrationWindowStats>
}

export interface CalibrationWindow {
  start: string
  end: string
  months: number
  requested_months?: number | null
  is_short?: boolean
  asset_order: string[]
  matrix: number[][]
}

export interface CalibrationSnapshot {
  generated_at: string
  inflation_assumption: number
  asset_order: string[]
  assets: Record<string, CalibrationAsset>
  correlations: Record<string, CalibrationWindow>
  data_version: string
  disclaimer: string
}

export interface DefaultsResponse {
  request: ScenarioRequest
  presets: Record<string, ScenarioPreset>
  calibration: CalibrationSnapshot | null
}
