import { useEffect, useRef, useState } from 'react'
import type {
  AnalysisMetric,
  AnalysisMode,
  AnalysisResponse,
  WhatIfVariant,
} from '../types'
import { createAnalysis } from '../api'

function metricsByKey(variant: WhatIfVariant): Map<string, AnalysisMetric> {
  return new Map(variant.metrics.map((metric) => [metric.key, metric]))
}

function MetricCell({ metric }: { metric: AnalysisMetric | undefined }) {
  if (!metric) return <span className="analysis-missing">—</span>
  return (
    <span className="analysis-metric">
      <span>{metric.formatted}</span>
      {metric.delta_formatted ? (
        <span className={`analysis-delta ${metric.better}`}>
          {metric.delta_formatted}
          {metric.better !== 'neutral' ? (
            <em>{metric.better === 'better' ? '改善' : '变差'}</em>
          ) : null}
        </span>
      ) : (
        <span className="analysis-delta neutral">基准</span>
      )}
    </span>
  )
}

export default function AnalysisPanel({
  mode,
  runId,
}: {
  mode: AnalysisMode
  runId: string
}) {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestSeq = useRef(0)
  const previousRun = useRef(`${mode}:${runId}`)

  useEffect(() => {
    // A new run must not inherit the previous run's analysis, and a request
    // still in flight for the old run must not write into the new state.
    const key = `${mode}:${runId}`
    if (previousRun.current === key) return
    previousRun.current = key
    requestSeq.current += 1
    setAnalysis(null)
    setBusy(false)
    setError(null)
  }, [runId, mode])

  const runAnalysis = async (force = false) => {
    const seq = ++requestSeq.current
    setBusy(true)
    setError(null)
    try {
      const payload = await createAnalysis({
        mode,
        run_id: runId,
        force,
      })
      if (seq === requestSeq.current) setAnalysis(payload)
    } catch (err) {
      if (seq === requestSeq.current) {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      if (seq === requestSeq.current) setBusy(false)
    }
  }

  return (
    <section className="card analysis-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">AI 分析与建议</h2>
          <p className="card-sub">
            先由后端计算一组单参数 what-if，再把真实结果交给模型；模型不直接算数。
          </p>
        </div>
        <div className="analysis-head-actions">
          {analysis ? (
            <span
              className={`badge ${
                analysis.source === 'llm' ? 'badge-llm' : 'badge-template'
              }`}
            >
              <span className="badge-dot" />
              {analysis.source === 'llm' ? 'AI 分析' : '模板分析'}
            </span>
          ) : null}
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => runAnalysis(Boolean(analysis))}
          >
            {busy ? '分析中…' : analysis ? '重新分析' : '生成 AI 分析与建议'}
          </button>
        </div>
      </div>

      {analysis ? (
        <p className="analysis-meta">
          分析编号 {analysis.analysis_id} ·{' '}
          {analysis.source === 'llm'
            ? `模型 ${analysis.model ?? 'LLM'}`
            : '模板生成'}
          {' · '}
          {analysis.variants.length - 1} 组局部 what-if
        </p>
      ) : null}

      {busy ? (
        <div className="analysis-loading">
          <span className="analysis-spinner" aria-hidden="true" />
          正在计算局部 what-if 并请求模型，通常需要几秒；这次只改变一个参数。
        </div>
      ) : null}

      {error ? (
        <div className="error-box">
          <strong>分析失败</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {analysis ? (
        <div className="analysis-body">
          {analysis.warnings.length > 0 ? (
            <div className="warning-box">
              {analysis.warnings.map((warning, index) => (
                <div key={index}>{warning}</div>
              ))}
            </div>
          ) : null}

          <p className="explain-summary">{analysis.summary}</p>

          <div className="analysis-section">
            <h4>结果解读</h4>
            <ul className="explain-list">
              {analysis.findings.map((finding, index) => (
                <li key={index}>{finding}</li>
              ))}
            </ul>
          </div>

          <div className="analysis-section analysis-suggestions">
            <div className="analysis-section-head">
              <h4>可以考虑的方向</h4>
              <span className="role-tag">情景建议 · 非投资建议</span>
            </div>
            <ol className="suggestion-list">
              {analysis.suggestions.map((suggestion, index) => (
                <li key={index}>{suggestion}</li>
              ))}
            </ol>
          </div>

          <div className="analysis-section">
            <h4>局部 what-if 对比</h4>
            <div className="table-scroll">
              <table className="mini-table analysis-table">
                <thead>
                  <tr>
                    <th>情景</th>
                    {analysis.metric_order.map((key) => (
                      <th key={key}>{analysis.metric_labels[key] ?? key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {analysis.variants.map((variant) => {
                    const metrics = metricsByKey(variant)
                    return (
                      <tr
                        key={variant.key}
                        className={
                          variant.key === 'baseline'
                            ? 'analysis-baseline-row'
                            : undefined
                        }
                      >
                        <td>
                          <strong>{variant.label}</strong>
                          <span className="analysis-variant-desc">
                            {variant.description}
                          </span>
                        </td>
                        {analysis.metric_order.map((key) => (
                          <td key={key}>
                            <MetricCell metric={metrics.get(key)} />
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="chart-footnote">
              每次只改变一个参数，其他假设保持不变；这不是全局最优搜索。
              期末金额为今日购买力，收益和回撤均为模型或历史实现值。
            </p>
          </div>

          <div className="caveat-box">
            <h4>分析边界</h4>
            <ul>
              {analysis.caveats.map((caveat, index) => (
                <li key={index}>{caveat}</li>
              ))}
            </ul>
          </div>

          <p className="analysis-disclaimer">{analysis.disclaimer}</p>

          <details className="table-view">
            <summary>引用指标（{analysis.metric_refs.length}）</summary>
            <div className="chip-row">
              {analysis.metric_refs.map((ref) => (
                <code className="chip" key={ref}>
                  {ref}
                </code>
              ))}
            </div>
            <p className="chart-footnote">
              建议中的数值只能来自这些指标；占位符在渲染层注入，模型不直接书写数字。
            </p>
          </details>
        </div>
      ) : null}
    </section>
  )
}
