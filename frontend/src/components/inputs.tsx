import { useEffect, useRef, useState, type ReactNode } from 'react'

export function Field({
  label,
  hint,
  full,
  children,
}: {
  label: string
  hint?: string
  full?: boolean
  children: ReactNode
}) {
  return (
    <label className={full ? 'field full' : 'field'}>
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  )
}

export function NumberInput({
  value,
  onChange,
  step = 1,
  min,
  max,
  suffix,
}: {
  value: number
  onChange: (value: number) => void
  step?: number
  min?: number
  max?: number
  suffix?: string
}) {
  const [draft, setDraft] = useState(String(value))
  const [focused, setFocused] = useState(false)
  const lastValid = useRef(value)

  useEffect(() => {
    if (!focused) {
      setDraft(String(value))
      lastValid.current = value
    }
  }, [value, focused])

  return (
    <span className="input-wrap">
      <input
        type="number"
        value={draft}
        step={step}
        min={min}
        max={max}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false)
          const parsed = Number(draft)
          if (draft.trim() === '' || !Number.isFinite(parsed)) {
            setDraft(String(lastValid.current))
          } else {
            lastValid.current = parsed
            setDraft(String(parsed))
          }
        }}
        onChange={(event) => {
          const raw = event.target.value
          setDraft(raw)
          // Keep an empty field empty while editing; do not force it to 0.
          if (raw.trim() === '') return
          const parsed = Number(raw)
          if (Number.isFinite(parsed)) {
            lastValid.current = parsed
            onChange(parsed)
          }
        }}
      />
      {suffix ? <span className="unit">{suffix}</span> : null}
    </span>
  )
}

export function PercentInput({
  value,
  onChange,
}: {
  value: number
  onChange: (value: number) => void
}) {
  return (
    <NumberInput
      value={Number((value * 100).toFixed(2))}
      step={0.1}
      suffix="%"
      onChange={(next) => onChange(next / 100)}
    />
  )
}

export function WanInput({
  value,
  onChange,
}: {
  value: number
  onChange: (value: number) => void
}) {
  return (
    <NumberInput
      value={Number((value / 10_000).toFixed(2))}
      step={0.5}
      suffix="万元"
      onChange={(next) => onChange(next * 10_000)}
    />
  )
}
