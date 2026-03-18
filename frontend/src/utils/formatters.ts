export function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '-'
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtPct(n: number): string {
  return (n * 100).toFixed(1) + '%'
}

export function formulaLabel(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export function ruleIdLabel(id: string): string {
  return id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export function regulationLabel(reg: string): string {
  const map: Record<string, string> = {
    reg_t: 'Reg T',
    finra_4210: 'FINRA 4210',
    house: 'House',
    reg_sho: 'Reg SHO',
    finra_reporting: 'FINRA Reporting',
    sec: 'SEC',
  }
  return map[reg] || reg
}

export function regulationBadge(reg: string): string {
  const map: Record<string, string> = {
    reg_t: 'badge-amber',
    finra_4210: 'badge-blue',
    house: 'badge-purple',
    reg_sho: 'badge-cyan',
    finra_reporting: 'badge-green',
    sec: 'badge-red',
  }
  return map[reg] || 'badge-muted'
}
