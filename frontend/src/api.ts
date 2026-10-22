import type {
  AnalysisRequest,
  AnalysisResponse,
  CashflowAssumptionPreview,
  CashflowBalance,
  CashflowBalanceInput,
  CashflowImportBatch,
  CashflowImportResult,
  CashflowMapping,
  CashflowPreview,
  CashflowRule,
  CashflowRuleInput,
  CashflowSummary,
  CashflowTransaction,
  CashflowTransactionList,
  CashflowTransactionPatch,
  CompareResponse,
  DefaultsResponse,
  HistoryMetaResponse,
  HistoryRequest,
  HistoryResponse,
  RunListItem,
  RunResponse,
  ScenarioRequest,
  SimpleRequest,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const text = await response.text()
    let detail: unknown = text
    try {
      const parsed = JSON.parse(text)
      detail = parsed.detail ?? text
    } catch {
      // Keep the raw text.
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as T
}

export function getDefaults(): Promise<DefaultsResponse> {
  return request<DefaultsResponse>('/api/defaults')
}

export function createRun(body: ScenarioRequest): Promise<RunResponse> {
  return request<RunResponse>('/api/runs', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createSimpleRun(body: SimpleRequest): Promise<RunResponse> {
  return request<RunResponse>('/api/simple', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getHistoryMeta(): Promise<HistoryMetaResponse> {
  return request<HistoryMetaResponse>('/api/history/meta')
}

export function createHistoryBacktest(
  body: HistoryRequest,
): Promise<HistoryResponse> {
  return request<HistoryResponse>('/api/history/backtest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getHistoryRun(runId: string): Promise<HistoryResponse> {
  return request<HistoryResponse>(
    `/api/history/runs/${encodeURIComponent(runId)}`,
  )
}

export function createAnalysis(
  body: AnalysisRequest,
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>('/api/analysis', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getAnalysis(analysisId: string): Promise<AnalysisResponse> {
  return request<AnalysisResponse>(
    `/api/analysis/${encodeURIComponent(analysisId)}`,
  )
}

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    const text = await response.text()
    let detail: unknown = text
    try {
      const parsed = JSON.parse(text)
      detail = parsed.detail ?? text
    } catch {
      // Keep raw text.
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as T
}

export function previewCashflow(
  file: File,
  source: string,
): Promise<CashflowPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('source', source)
  return requestForm<CashflowPreview>('/api/cashflow/preview', form)
}

export function listCashflowImports(): Promise<CashflowImportBatch[]> {
  return request<CashflowImportBatch[]>('/api/cashflow/imports')
}

export function deleteCashflowImport(
  importId: string,
): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(
    `/api/cashflow/imports/${encodeURIComponent(importId)}`,
    { method: 'DELETE' },
  )
}

export function importCashflow(
  file: File,
  source: string,
  account: string,
  mapping: CashflowMapping,
): Promise<CashflowImportResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('source', source)
  form.append('account', account)
  form.append('mapping', JSON.stringify(mapping))
  return requestForm<CashflowImportResult>('/api/cashflow/import', form)
}

export function listCashflowTransactions(params: {
  fromDate?: string
  toDate?: string
  limit?: number
  offset?: number
  direction?: string
  category?: string
}): Promise<CashflowTransactionList> {
  const search = new URLSearchParams()
  if (params.fromDate) search.set('from_date', params.fromDate)
  if (params.toDate) search.set('to_date', params.toDate)
  search.set('limit', String(params.limit ?? 200))
  search.set('offset', String(params.offset ?? 0))
  if (params.direction) search.set('direction', params.direction)
  if (params.category) search.set('category', params.category)
  return request<CashflowTransactionList>(
    `/api/cashflow/transactions?${search.toString()}`,
  )
}

export function updateCashflowTransaction(
  id: number,
  patch: CashflowTransactionPatch,
): Promise<CashflowTransaction> {
  return request<CashflowTransaction>(`/api/cashflow/transactions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function listCashflowRules(): Promise<CashflowRule[]> {
  return request<CashflowRule[]>('/api/cashflow/rules')
}

export function createCashflowRule(
  rule: CashflowRuleInput,
): Promise<CashflowRule> {
  return request<CashflowRule>('/api/cashflow/rules', {
    method: 'POST',
    body: JSON.stringify(rule),
  })
}

export function deleteCashflowRule(id: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/cashflow/rules/${id}`, {
    method: 'DELETE',
  })
}

export function reapplyCashflowRules(): Promise<{ updated: number }> {
  return request<{ updated: number }>('/api/cashflow/reapply-rules', {
    method: 'POST',
  })
}

export function listCashflowBalances(): Promise<CashflowBalance[]> {
  return request<CashflowBalance[]>('/api/cashflow/balances')
}

export function upsertCashflowBalance(
  balance: CashflowBalanceInput,
): Promise<CashflowBalance> {
  return request<CashflowBalance>('/api/cashflow/balances', {
    method: 'POST',
    body: JSON.stringify(balance),
  })
}

export function deleteCashflowBalance(
  id: number,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/cashflow/balances/${id}`, {
    method: 'DELETE',
  })
}

export function importCashflowBalances(file: File): Promise<{
  row_count: number
  imported: number
  skipped: number
  warnings: string[]
}> {
  const form = new FormData()
  form.append('file', file)
  return requestForm('/api/cashflow/balances/import', form)
}

export function getCashflowSummary(params?: {
  fromDate?: string
  toDate?: string
}): Promise<CashflowSummary> {
  const search = new URLSearchParams()
  if (params?.fromDate) search.set('from_date', params.fromDate)
  if (params?.toDate) search.set('to_date', params.toDate)
  return request<CashflowSummary>(
    `/api/cashflow/summary?${search.toString()}`,
  )
}

export function getCashflowAssumptions(
  window = 12,
): Promise<CashflowAssumptionPreview> {
  return request<CashflowAssumptionPreview>(
    `/api/cashflow/assumptions?window=${window}`,
  )
}

export function compareRuns(body: ScenarioRequest[]): Promise<CompareResponse> {
  return request<CompareResponse>('/api/compare', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listRuns(): Promise<RunListItem[]> {
  return request<RunListItem[]>('/api/runs?limit=12')
}

export function getRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/runs/${encodeURIComponent(runId)}`)
}
