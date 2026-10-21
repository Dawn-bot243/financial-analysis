import { useState } from 'react'
import type { RunResponse } from '../types'
import { fmtDate } from '../format'

export default function RunMeta({ run }: { run: RunResponse }) {
  const [copied, setCopied] = useState(false)
  const [copiedLink, setCopiedLink] = useState(false)

  const copyRunId = async () => {
    try {
      await navigator.clipboard.writeText(run.run_id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  const copyLink = async () => {
    const url = new URL(window.location.href)
    url.searchParams.set('run', run.run_id)
    try {
      await navigator.clipboard.writeText(url.toString())
      setCopiedLink(true)
      window.setTimeout(() => setCopiedLink(false), 1500)
    } catch {
      setCopiedLink(false)
    }
  }

  return (
    <section className="card run-meta-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">运行快照</h2>
          <p className="card-sub">
            run_id 是假设集、数据版本、代码指纹、随机种子与解释模式的内容哈希。
          </p>
        </div>
        <div className="card-head-actions">
          <button type="button" className="copy-btn" onClick={copyLink}>
            {copiedLink ? '已复制' : '复制链接'}
          </button>
          <button type="button" className="copy-btn" onClick={copyRunId}>
            {copied ? '已复制' : '复制 run_id'}
          </button>
        </div>
      </div>

      <div className="meta-grid">
        <div className="meta-item">
          run_id
          <strong className="mono">{run.run_id}</strong>
        </div>
        <div className="meta-item">
          生成时间
          <strong>{fmtDate(run.created_at)}</strong>
        </div>
        <div className="meta-item">
          路径 / 种子
          <strong>
            {run.request.n_paths.toLocaleString('zh-CN')} / {run.request.seed}
          </strong>
        </div>
        <div className="meta-item">
          代码版本 / 指纹
          <strong className="mono">
            {run.code_version} / {run.code_fingerprint}
          </strong>
        </div>
        <div className="meta-item">
          数据版本 / 校准窗口
          <strong className="mono">
            {run.data_version} / {run.request.calibration_window ?? '手动'}
          </strong>
        </div>
      </div>

      <details className="meta-details">
        <summary>参数快照（完整请求）</summary>
        <pre>{JSON.stringify(run.request, null, 2)}</pre>
      </details>

      {run.explanation.templates ? (
        <details className="meta-details">
          <summary>解释模板（渲染前）</summary>
          <pre>{JSON.stringify(run.explanation.templates, null, 2)}</pre>
        </details>
      ) : null}

      <p className="disclaimer-footer">
        本工具仅用于情景推演，不构成投资建议。所有收益率为假设，不是预测；
        实际结果可能显著不同。
      </p>
    </section>
  )
}
