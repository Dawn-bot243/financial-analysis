import type { Explanation } from '../types'

export default function ExplanationPanel({
  explanation,
}: {
  explanation: Explanation
}) {
  const isLlm = explanation.source === 'llm'
  return (
    <section className="card explanation-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">解释</h2>
          <p className="card-sub">
            {isLlm
              ? `数值摘要结构化输入 · ${explanation.model ?? 'LLM'}`
              : '模板生成 · 未调用大模型'}
          </p>
        </div>
        <span className={`badge ${isLlm ? 'badge-llm' : 'badge-template'}`}>
          <span className="badge-dot" />
          {isLlm ? 'AI 解释' : '模板解释'}
        </span>
      </div>

      <p className="explain-summary">{explanation.summary}</p>
      <ul className="explain-list">
        {explanation.bullets.map((bullet, index) => (
          <li key={index}>{bullet}</li>
        ))}
      </ul>

      <div className="caveat-box">
        <h4>模型边界</h4>
        <ul>
          {explanation.caveats.map((caveat, index) => (
            <li key={index}>{caveat}</li>
          ))}
        </ul>
      </div>

      <details className="table-view">
        <summary>引用指标（{explanation.metric_refs.length}）</summary>
        <div className="chip-row">
          {explanation.metric_refs.map((ref) => (
            <code className="chip" key={ref}>
              {ref}
            </code>
          ))}
        </div>
        <p className="chart-footnote">
          解释中的数值只能来自这些指标；占位符在渲染层注入，模型不直接书写数字。
        </p>
      </details>
    </section>
  )
}
