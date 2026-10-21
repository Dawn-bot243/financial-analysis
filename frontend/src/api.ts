import type {
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
