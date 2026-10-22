export function fmtMoney(yuan: number): string {
  if (Math.abs(yuan) >= 10_000) {
    return `${(yuan / 10_000).toFixed(1)}万元`
  }
  return `${yuan.toFixed(0)}元`
}

export function fmtYuan(yuan: number): string {
  return `${yuan.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}元`
}

export function fmtPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function fmtPct0(value: number): string {
  return `${(value * 100).toFixed(0)}%`
}

export function toWan(yuan: number): number {
  return yuan / 10_000
}

export function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
