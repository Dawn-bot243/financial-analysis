import { useEffect, useState } from 'react'
import type {
  CalibrationSnapshot,
  CompareResponse,
  RunListItem,
  RunResponse,
} from './types'
import { compareRuns, createRun, getDefaults, getRun, listRuns } from './api'
import {
  calibrationAssets,
  calibrationLabel,
  formFromRequest,
  newPurchase,
  requestFromForm,
  validateForm,
  type AssetForm,
  type EventForm,
  type EventKind,
  type FormState,
  type HoldingForm,
  type LiabilityForm,
  type PathVariant,
  type PurchaseForm,
} from './form'
import AssumptionsForm from './components/AssumptionsForm'
import HistoryPanel from './components/HistoryPanel'
import ResultsView from './components/ResultsView'
import ComparisonTable from './components/ComparisonTable'
import SimpleView from './components/SimpleView'
import HistoryView from './components/HistoryView'

function EmptyState({ mode }: { mode: 'result' | 'compare' | 'paths' }) {
  return (
    <div className="empty-card">
      <div className="empty-mark">10Y</div>
      <h2>
        {mode === 'result'
          ? '还没有推演结果'
          : mode === 'compare'
            ? '还没有窗口对比'
            : '还没有人生道路对比'}
      </h2>
      <p>
        {mode === 'result'
          ? '在上面设定家庭现金流、初始资产、投资策略和人生事件，点击“运行推演”。你会得到未来各时点的分位路径、最大回撤分布和事件通过率。'
          : mode === 'compare'
            ? '点击“窗口对比”，用近 5 / 10 / 15 年的历史校准假设和同一组随机路径做对照。'
            : '在“人生道路对比”里添加路径，勾选每条路径包含的事件，例如“买车 vs 不买车”，然后运行对比。'}
      </p>
    </div>
  )
}

export default function App() {
  const [calibration, setCalibration] = useState<CalibrationSnapshot | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [result, setResult] = useState<RunResponse | null>(null)
  const [comparison, setComparison] = useState<CompareResponse | null>(null)
  const [pathComparison, setPathComparison] = useState<CompareResponse | null>(
    null,
  )
  const [history, setHistory] = useState<RunListItem[]>([])
  const [busy, setBusy] = useState<'run' | 'compare' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'result' | 'compare' | 'paths'>('result')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [mode, setMode] = useState<'simple' | 'full' | 'history'>(() => {
    const requestedRun = new URLSearchParams(window.location.search).get('run')
    if (requestedRun) return 'full'
    const stored = localStorage.getItem('finance-mode')
    if (stored === 'full' || stored === 'history') return stored
    return 'simple'
  })

  const switchMode = (next: 'simple' | 'full' | 'history') => {
    setMode(next)
    localStorage.setItem('finance-mode', next)
    const url = new URL(window.location.href)
    if (next === 'full') {
      if (activeRunId) url.searchParams.set('run', activeRunId)
    } else {
      url.searchParams.delete('run')
    }
    window.history.replaceState(null, '', url)
  }

  useEffect(() => {
    let alive = true
    const requestedRun = new URLSearchParams(window.location.search).get('run')

    getDefaults()
      .then((data) => {
        if (!alive) return
        setCalibration(data.calibration)
        setForm((previous) => previous ?? formFromRequest(data.request))
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : String(err))
      })

    if (requestedRun) {
      getRun(requestedRun)
        .then((run) => {
          if (!alive) return
          setResult(run)
          setForm(formFromRequest(run.request))
          setActiveRunId(run.run_id)
          setMode('full')
          window.setTimeout(() => {
            document
              .getElementById('results')
              ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }, 250)
        })
        .catch((err) => {
          if (alive) setError(err instanceof Error ? err.message : String(err))
        })
    }

    listRuns()
      .then((items) => {
        if (alive) setHistory(items)
      })
      .catch(() => {
        // History is non-blocking.
      })

    return () => {
      alive = false
    }
  }, [])

  const refreshHistory = async () => {
    try {
      setHistory(await listRuns())
    } catch {
      // History is non-blocking.
    }
  }

  const syncRunUrl = (runId: string) => {
    const url = new URL(window.location.href)
    url.searchParams.set('run', runId)
    window.history.replaceState(null, '', url)
  }

  const scrollToResults = () => {
    window.setTimeout(() => {
      document
        .getElementById('results')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 60)
  }

  const updateForm = (patch: Partial<FormState>) => {
    setForm((previous) => (previous ? { ...previous, ...patch } : previous))
  }

  const updateAsset = (index: number, patch: Partial<AssetForm>) => {
    setForm((previous) => {
      if (!previous) return previous
      const assets = previous.assets.map((asset, assetIndex) =>
        assetIndex === index ? { ...asset, ...patch } : asset,
      )
      return { ...previous, assets }
    })
  }

  const updateHolding = (index: number, patch: Partial<HoldingForm>) => {
    setForm((previous) => {
      if (!previous) return previous
      const holdings = previous.holdings.map((holding, holdingIndex) =>
        holdingIndex === index ? { ...holding, ...patch } : holding,
      )
      return { ...previous, holdings }
    })
  }

  const updateLiability = (index: number, patch: Partial<LiabilityForm>) => {
    setForm((previous) => {
      if (!previous) return previous
      const liabilities = previous.liabilities.map((liability, liabilityIndex) =>
        liabilityIndex === index ? { ...liability, ...patch } : liability,
      )
      return { ...previous, liabilities }
    })
  }

  const addLiability = () => {
    setForm((previous) => {
      if (!previous) return previous
      const names = new Set(previous.liabilities.map((item) => item.name))
      let number = previous.liabilities.length + 1
      let name = `负债 ${number}`
      while (names.has(name)) {
        number += 1
        name = `负债 ${number}`
      }
      return {
        ...previous,
        liabilities: [
          ...previous.liabilities,
          {
            name,
            balance: 0,
            annualRate: 0.035,
            remainingMonths: 300,
            linkedHolding: null,
          },
        ],
      }
    })
  }

  const removeLiability = (index: number) => {
    setForm((previous) => {
      if (!previous) return previous
      return {
        ...previous,
        liabilities: previous.liabilities.filter(
          (_, liabilityIndex) => liabilityIndex !== index,
        ),
      }
    })
  }

  const updateEvent = (index: number, patch: Partial<EventForm>) => {
    setForm((previous) => {
      if (!previous) return previous
      const events = previous.events.map((event, eventIndex) =>
        eventIndex === index ? { ...event, ...patch } : event,
      )
      return { ...previous, events }
    })
  }

  const updatePurchase = (index: number, patch: Partial<PurchaseForm>) => {
    setForm((previous) => {
      if (!previous) return previous
      const events = previous.events.map((event, eventIndex) => {
        if (eventIndex !== index || !event.purchase) return event
        return { ...event, purchase: { ...event.purchase, ...patch } }
      })
      return { ...previous, events }
    })
  }

  const addEvent = (kind: EventKind) => {
    setForm((previous) => {
      if (!previous) return previous
      const startAge = previous.currentAge + 1
      const id = `event-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
      let event: EventForm
      if (kind === 'purchase') {
        event = {
          id,
          kind,
          name: '买房',
          startAge,
          endAge: null,
          windowYears: 3,
          oneOffExpense: 0,
          monthlyIncome: 0,
          monthlyExpense: 1_000,
          purchase: newPurchase('real_estate', startAge),
        }
      } else if (kind === 'recurring_income') {
        event = {
          id,
          kind,
          name: '持续收入',
          startAge,
          endAge: startAge + 3,
          windowYears: 0,
          oneOffExpense: 0,
          monthlyIncome: 3_000,
          monthlyExpense: 0,
          purchase: null,
        }
      } else if (kind === 'recurring_expense') {
        event = {
          id,
          kind,
          name: '持续支出',
          startAge,
          endAge: startAge + 3,
          windowYears: 0,
          oneOffExpense: 0,
          monthlyIncome: 0,
          monthlyExpense: 1_000,
          purchase: null,
        }
      } else {
        event = {
          id,
          kind: 'one_off',
          name: '一次性支出',
          startAge,
          endAge: null,
          windowYears: 0,
          oneOffExpense: 100_000,
          monthlyIncome: 0,
          monthlyExpense: 0,
          purchase: null,
        }
      }
      return { ...previous, events: [...previous.events, event] }
    })
  }

  const removeEvent = (index: number) => {
    setForm((previous) => {
      if (!previous) return previous
      return {
        ...previous,
        events: previous.events.filter(
          (_, eventIndex) => eventIndex !== index,
        ),
      }
    })
  }

  const applyCalibration = (window: string) => {
    if (!calibration) return
    const assets = calibrationAssets(calibration, window)
    const correlation = calibration.correlations[window].matrix.map((row) => [
      ...row,
    ])
    setForm((previous) =>
      previous
        ? {
            ...previous,
            assets,
            correlation,
            calibrationWindow: window,
            dataVersion: calibration.data_version,
          }
        : previous,
    )
    setPathComparison(null)
  }

  const addPathVariant = () => {
    setForm((previous) => {
      if (!previous || previous.pathVariants.length >= 4) return previous
      const number = previous.pathVariants.length + 1
      return {
        ...previous,
        pathVariants: [
          ...previous.pathVariants,
          {
            id: `path-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            name: `对比路径 ${number}`,
            includedEventIds: previous.events.map((event) => event.id),
          },
        ],
      }
    })
  }

  const updatePathVariant = (index: number, patch: Partial<PathVariant>) => {
    setForm((previous) => {
      if (!previous) return previous
      const pathVariants = previous.pathVariants.map((variant, variantIndex) =>
        variantIndex === index ? { ...variant, ...patch } : variant,
      )
      return { ...previous, pathVariants }
    })
  }

  const removePathVariant = (index: number) => {
    setForm((previous) => {
      if (!previous) return previous
      return {
        ...previous,
        pathVariants: previous.pathVariants.filter(
          (_, variantIndex) => variantIndex !== index,
        ),
      }
    })
  }

  const handlePathCompare = async () => {
    if (!form) return
    const validation = validateForm(form)
    if (validation) {
      setError(validation)
      return
    }
    if (form.events.length === 0) {
      setError('先在“人生事件”里添加至少一个事件，再对比路径。')
      return
    }
    if (form.pathVariants.length === 0) {
      setError('先添加至少一条对比路径。')
      return
    }
    const base = requestFromForm(form)
    base.name = form.name.trim() || '基准路径'
    const baseEvents = base.household.events
    const requests = [base]
    for (const variant of form.pathVariants) {
      const request = structuredClone(base)
      request.name = variant.name.trim() || '对比路径'
      const included = new Set(variant.includedEventIds)
      request.household.events = baseEvents.filter((_, index) => {
        const formEvent = form.events[index]
        return formEvent ? included.has(formEvent.id) : false
      })
      request.include_explanation = false
      requests.push(request)
    }
    const names = requests.map((request) => request.name)
    if (new Set(names).size !== names.length) {
      setError('对比路径名称不能重复。')
      return
    }

    setBusy('compare')
    setError(null)
    try {
      const data = await compareRuns(requests)
      setPathComparison(data)
      setTab('paths')
      await refreshHistory()
      scrollToResults()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  const handleRun = async () => {
    if (!form) return
    const validation = validateForm(form)
    if (validation) {
      setError(validation)
      return
    }
    setBusy('run')
    setError(null)
    try {
      const run = await createRun(requestFromForm(form))
      setResult(run)
      setActiveRunId(run.run_id)
      setTab('result')
      syncRunUrl(run.run_id)
      await refreshHistory()
      scrollToResults()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  const handleCompare = async () => {
    if (!form) return
    if (!calibration) {
      setError('没有校准快照，无法做窗口对比。')
      return
    }
    const validation = validateForm(form)
    if (validation) {
      setError(validation)
      return
    }
    const windows = ['5y', '10y', '15y'].filter(
      (window) => calibration.correlations[window],
    )
    if (windows.length < 2) {
      setError('可用的校准窗口不足，至少需要两个。')
      return
    }
    const base = requestFromForm(form)
    const requests = windows.map((window) => {
      const request = structuredClone(base)
      request.name = calibrationLabel(calibration, window)
      request.market.assets = calibrationAssets(calibration, window).map(
        (asset) => ({
          name: asset.name,
          label: asset.label,
          role: asset.role,
          expected_real_return: asset.expectedReturn,
          volatility: asset.volatility,
          expense_ratio: asset.expenseRatio,
          liquid: true,
        }),
      )
      request.market.correlation = calibration.correlations[window].matrix.map(
        (row) => [...row],
      )
      request.calibration_window = window
      request.data_version = calibration.data_version
      request.include_explanation = false
      return request
    })

    setBusy('compare')
    setError(null)
    try {
      const data = await compareRuns(requests)
      setComparison(data)
      setTab('compare')
      await refreshHistory()
      scrollToResults()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  const loadRun = async (runId: string) => {
    try {
      const run = await getRun(runId)
      setResult(run)
      setForm(formFromRequest(run.request))
      setActiveRunId(run.run_id)
      setMode('full')
      setTab('result')
      setPathComparison(null)
      syncRunUrl(run.run_id)
      setError(null)
      scrollToResults()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <p className="eyebrow">PERSONAL FINANCE LAB</p>
          <h1>家庭财务情景推演</h1>
          <p className="subtitle">
            确定性数值计算 · 分布输出 · 假设可追溯
          </p>
        </div>
        <div className="header-note">非投资建议</div>
      </header>

      <div className="disclaimer">
        本工具仅用于情景推演，不构成投资建议。所有金额均为今日购买力，已按 2%
        通胀折算；所有收益、波动和相关性均为假设或历史校准，不是预测；实际结果可能显著不同。
      </div>

      <div className="mode-switch" role="tablist" aria-label="版本切换">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'simple'}
          className={mode === 'simple' ? 'mode-btn active' : 'mode-btn'}
          onClick={() => switchMode('simple')}
        >
          简版定投
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'full'}
          className={mode === 'full' ? 'mode-btn active' : 'mode-btn'}
          onClick={() => switchMode('full')}
        >
          完整版
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'history'}
          className={mode === 'history' ? 'mode-btn active' : 'mode-btn'}
          onClick={() => switchMode('history')}
        >
          历史定投
        </button>
      </div>

      {mode === 'history' ? (
        <HistoryView />
      ) : mode === 'simple' ? (
        calibration ? (
          <SimpleView calibration={calibration} />
        ) : (
          <div className="loading-card">正在加载历史校准…</div>
        )
      ) : form ? (
        <>
          <AssumptionsForm
            form={form}
            calibration={calibration}
            busy={busy}
            onChange={updateForm}
            onAssetChange={updateAsset}
            onHoldingChange={updateHolding}
            onLiabilityChange={updateLiability}
            onAddLiability={addLiability}
            onRemoveLiability={removeLiability}
            onEventChange={updateEvent}
            onPurchaseChange={updatePurchase}
            onAddEvent={addEvent}
            onRemoveEvent={removeEvent}
            onAddPathVariant={addPathVariant}
            onPathVariantChange={updatePathVariant}
            onRemovePathVariant={removePathVariant}
            onApplyCalibration={applyCalibration}
            onRun={handleRun}
            onCompare={handleCompare}
            onRunPathCompare={handlePathCompare}
          />

          <main className="content" id="results">
            {error ? (
              <div className="error-box">
                <strong>无法完成</strong>
                <span>{error}</span>
              </div>
            ) : null}

            <div className="tabs">
              <button
                type="button"
                className={tab === 'result' ? 'tab active' : 'tab'}
                onClick={() => setTab('result')}
              >
                单情景推演
              </button>
              <button
                type="button"
                className={tab === 'compare' ? 'tab active' : 'tab'}
                onClick={() => setTab('compare')}
              >
                窗口对比
              </button>
              <button
                type="button"
                className={tab === 'paths' ? 'tab active' : 'tab'}
                onClick={() => setTab('paths')}
              >
                人生道路对比
              </button>
            </div>

            {tab === 'result' ? (
              result ? (
                <ResultsView run={result} />
              ) : (
                <EmptyState mode="result" />
              )
            ) : tab === 'compare' ? (
              comparison ? (
                <ComparisonTable comparison={comparison} mode="window" />
              ) : (
                <EmptyState mode="compare" />
              )
            ) : pathComparison ? (
              <ComparisonTable comparison={pathComparison} mode="path" />
            ) : (
              <EmptyState mode="paths" />
            )}
          </main>

          <div className="history-section">
            <HistoryPanel
              items={history}
              activeRunId={activeRunId}
              onLoad={loadRun}
            />
          </div>
        </>
      ) : (
        <div className="loading-card">
          {error ? (
            <>
              <strong>加载默认假设失败</strong>
              <p>{error}</p>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => window.location.reload()}
              >
                重试
              </button>
            </>
          ) : (
            '正在加载默认假设与历史校准…'
          )}
        </div>
      )}
    </div>
  )
}
