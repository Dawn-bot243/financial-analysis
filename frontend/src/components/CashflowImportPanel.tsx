import { useEffect, useRef, useState } from 'react'
import type {
  CashflowImportBatch,
  CashflowImportResult,
  CashflowMapping,
  CashflowPreview,
} from '../types'
import {
  deleteCashflowImport,
  importCashflow,
  listCashflowImports,
  previewCashflow,
} from '../api'
import { Field } from './inputs'

const SOURCE_LABELS: Record<string, string> = {
  alipay: '支付宝 CSV',
  wechat: '微信支付 CSV',
  bank: '银行 CSV / Excel',
  generic: '通用 CSV / Excel',
}

function HeaderSelect({
  label,
  value,
  headers,
  onChange,
  optional = false,
}: {
  label: string
  value: string | null | undefined
  headers: string[]
  onChange: (value: string | null) => void
  optional?: boolean
}) {
  return (
    <label className="cashflow-field">
      <span>{label}</span>
      <select
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{optional ? '不映射' : '请选择'}</option>
        {headers.map((header) => (
          <option value={header} key={header}>
            {header}
          </option>
        ))}
      </select>
    </label>
  )
}

export default function CashflowImportPanel({
  onImported,
}: {
  onImported: () => void
}) {
  const [source, setSource] = useState('alipay')
  const [account, setAccount] = useState('支付宝')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CashflowPreview | null>(null)
  const [mapping, setMapping] = useState<CashflowMapping | null>(null)
  const [result, setResult] = useState<CashflowImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [imports, setImports] = useState<CashflowImportBatch[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  const loadImports = async () => {
    try {
      setImports(await listCashflowImports())
    } catch {
      // Non-blocking.
    }
  }

  useEffect(() => {
    loadImports()
  }, [])

  const handleFile = async (selected: File | null) => {
    setFile(selected)
    setPreview(null)
    setMapping(null)
    setResult(null)
    setError(null)
    if (!selected) return
    setBusy(true)
    try {
      const payload = await previewCashflow(selected, source)
      setPreview(payload)
      setMapping(payload.suggested_mapping)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const updateMapping = (patch: Partial<CashflowMapping>) => {
    setMapping((previous) => (previous ? { ...previous, ...patch } : previous))
  }

  const removeImport = async (importId: string) => {
    setBusy(true)
    try {
      await deleteCashflowImport(importId)
      setResult(null)
      await loadImports()
      onImported()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleImport = async () => {
    if (!file || !mapping) return
    if (!mapping.date) {
      setError('至少选择日期列。')
      return
    }
    if (mapping.amount_mode === 'two_columns') {
      if (!mapping.income_amount || !mapping.expense_amount) {
        setError('两列金额模式需要同时选择收入列和支出列。')
        return
      }
    } else if (!mapping.amount) {
      setError('至少选择金额列。')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const payload = await importCashflow(file, source, account, mapping)
      setResult(payload)
      await loadImports()
      onImported()
      if (inputRef.current) inputRef.current.value = ''
      setFile(null)
      setPreview(null)
      setMapping(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card cashflow-import-card">
      <div className="card-head">
        <div>
          <h2 className="card-title">导入历史流水</h2>
          <p className="card-sub">
            支付宝、微信或银行导出的 CSV/Excel；先预览并确认字段映射，再写入本地库。
            原始文件只存在本机，不会发给大模型。
          </p>
        </div>
      </div>

      <div className="cashflow-source-row">
        <Field label="来源">
          <select
            value={source}
            onChange={(event) => {
              const next = event.target.value
              setSource(next)
              const labels: Record<string, string> = {
                alipay: '支付宝',
                wechat: '微信支付',
                bank: '银行',
                generic: '通用',
              }
              setAccount(labels[next] ?? '')
            }}
          >
            {Object.entries(SOURCE_LABELS).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="账户/标签" hint="用于区分不同卡或平台">
          <input
            value={account}
            onChange={(event) => setAccount(event.target.value)}
            placeholder="例如 工资卡 / 支付宝"
          />
        </Field>
        <Field label="文件">
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx,.xls,text/csv"
            onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
          />
        </Field>
      </div>

      {busy ? <div className="cashflow-loading">正在读取文件…</div> : null}
      {error ? (
        <div className="error-box">
          <strong>导入未完成</strong>
          <span>{error}</span>
        </div>
      ) : null}
      {result ? (
        <div className="cashflow-import-result">
          <strong>已导入 {result.imported} 笔</strong>
          <span>
            文件 {result.filename} · 总行数 {result.row_count} · 重复{' '}
            {result.duplicates} · 跳过 {result.skipped}
          </span>
          {result.warnings.map((warning, index) => (
            <div className="form-note" key={index}>
              {warning}
            </div>
          ))}
        </div>
      ) : null}

      {imports.length > 0 ? (
        <details className="table-view cashflow-import-history">
          <summary>已导入批次（{imports.length}）</summary>
          <div className="table-scroll">
            <table className="mini-table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>来源</th>
                  <th>账户</th>
                  <th>导入</th>
                  <th>重复</th>
                  <th>跳过</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {imports.map((item) => (
                  <tr key={item.import_id}>
                    <td>{item.filename}</td>
                    <td>{item.source}</td>
                    <td>{item.account}</td>
                    <td>{item.imported}</td>
                    <td>{item.duplicates}</td>
                    <td>{item.skipped}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary small"
                        disabled={busy}
                        onClick={() => removeImport(item.import_id)}
                      >
                        删除批次
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}

      {preview && mapping ? (
        <div className="cashflow-mapping">
          <div className="section-head">
            <h3>字段映射</h3>
            <span className="section-note">
              表头第 {preview.header_row + 1} 行 · {preview.encoding} ·{' '}
              {preview.total_rows} 行
            </span>
          </div>
          <div className="cashflow-mapping-grid">
            <HeaderSelect
              label="日期"
              value={mapping.date}
              headers={preview.headers}
              onChange={(value) => updateMapping({ date: value ?? '' })}
            />
            {mapping.amount_mode === 'two_columns' ? (
              <>
                <HeaderSelect
                  label="收入金额列"
                  value={mapping.income_amount}
                  headers={preview.headers}
                  onChange={(value) =>
                    updateMapping({ income_amount: value })
                  }
                />
                <HeaderSelect
                  label="支出金额列"
                  value={mapping.expense_amount}
                  headers={preview.headers}
                  onChange={(value) =>
                    updateMapping({ expense_amount: value })
                  }
                />
              </>
            ) : (
              <HeaderSelect
                label="金额"
                value={mapping.amount}
                headers={preview.headers}
                onChange={(value) => updateMapping({ amount: value ?? '' })}
              />
            )}
            <HeaderSelect
              label="收/支"
              value={mapping.direction}
              headers={preview.headers}
              onChange={(value) => updateMapping({ direction: value })}
              optional
            />
            <HeaderSelect
              label="交易对方"
              value={mapping.counterparty}
              headers={preview.headers}
              onChange={(value) => updateMapping({ counterparty: value })}
              optional
            />
            <HeaderSelect
              label="商品/摘要"
              value={mapping.description}
              headers={preview.headers}
              onChange={(value) => updateMapping({ description: value })}
              optional
            />
            <HeaderSelect
              label="原始分类"
              value={mapping.category}
              headers={preview.headers}
              onChange={(value) => updateMapping({ category: value })}
              optional
            />
            <HeaderSelect
              label="账户列"
              value={mapping.account}
              headers={preview.headers}
              onChange={(value) => updateMapping({ account: value })}
              optional
            />
            <HeaderSelect
              label="交易状态"
              value={mapping.status}
              headers={preview.headers}
              onChange={(value) => updateMapping({ status: value })}
              optional
            />
            <label className="cashflow-field">
              <span>金额方向</span>
              <select
                value={mapping.amount_mode}
                onChange={(event) =>
                  updateMapping({
                    amount_mode: event.target
                      .value as CashflowMapping['amount_mode'],
                  })
                }
              >
                <option value="signed">正数收入 / 负数支出</option>
                <option value="positive_expense">正数支出 / 负数收入</option>
                <option value="absolute">全部按支出（需收/支列）</option>
                <option value="two_columns">收入/支出两列</option>
              </select>
            </label>
          </div>

          <div className="table-scroll cashflow-preview-table">
            <table className="mini-table">
              <thead>
                <tr>
                  {preview.headers.map((header) => (
                    <th key={header}>{header}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 5).map((row, index) => (
                  <tr key={index}>
                    {preview.headers.map((header) => (
                      <td key={header}>{row[header]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="inline-row spaced">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={handleImport}
            >
              {busy ? '导入中…' : '确认导入'}
            </button>
            <span className="form-note">
              导入后可在流水表里手动修正方向、分类、投资桶和“一次性”标记。
            </span>
          </div>
        </div>
      ) : null}
    </section>
  )
}
