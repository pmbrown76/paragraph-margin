import { useMemo } from 'react'
import type { Stats } from '../types'
import { regulationLabel, regulationBadge, formulaLabel } from '../utils/formatters'

interface Props {
  stats: Stats | null
  onReload: () => void
}

const BAR_COLORS: Record<string, string> = {
  reg_t: '#e5a00d',
  finra_4210: '#3b82f6',
  house: '#a855f7',
  reg_sho: '#06b6d4',
  finra_reporting: '#22c55e',
  sec: '#ef4444',
}

const FORMULA_COLORS = [
  '#3b82f6', '#22c55e', '#e5a00d', '#a855f7', '#06b6d4', '#ef4444',
  '#f97316', '#ec4899', '#14b8a6', '#6366f1',
]

function barStyle(value: number, max: number, color: string): React.CSSProperties {
  const pct = max > 0 ? (value / max) * 100 : 0
  return {
    background: color,
    borderRadius: 4,
    height: '100%',
    width: `${pct}%`,
    transition: 'width 0.3s ease',
  }
}

const barContainer: React.CSSProperties = {
  background: 'var(--bg-input)',
  borderRadius: 4,
  height: 24,
  width: '100%',
}

export function Overview({ stats, onReload }: Props) {
  const regulations = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.by_regulation)
      .filter(([, count]) => count > 0)
      .sort((a, b) => b[1] - a[1])
  }, [stats])

  const formulaTypes = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.by_formula_type)
      .filter(([, count]) => count > 0)
      .sort((a, b) => b[1] - a[1])
  }, [stats])

  if (!stats) {
    return <div className="panel">Loading statistics...</div>
  }

  const regMax = regulations.length > 0 ? regulations[0][1] : 0
  const formulaMax = formulaTypes.length > 0 ? formulaTypes[0][1] : 0

  return (
    <div>
      <div className="stat-grid">
        <div className="stat-card">
          <span className="label">Total Rules</span>
          <span className="value">{stats.total}</span>
        </div>
        <div className="stat-card">
          <span className="label">Disabled Rules</span>
          <span className="value">{stats.disabled_count}</span>
        </div>
        <div className="stat-card">
          <span className="label">Regulations</span>
          <span className="value">{regulations.length}</span>
        </div>
        <div className="stat-card">
          <span className="label">Formula Types</span>
          <span className="value">{formulaTypes.length}</span>
        </div>
      </div>

      <div className="panel">
        <h3>Rules by Regulation</h3>
        {regulations.map(([reg, count]) => (
          <div key={reg} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span className={`badge ${regulationBadge(reg)}`}>{regulationLabel(reg)}</span>
              <span>{count}</span>
            </div>
            <div style={barContainer}>
              <div style={barStyle(count, regMax, BAR_COLORS[reg] || '#6b7280')} />
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3>Rules by Formula Type</h3>
        {formulaTypes.map(([type, count], i) => (
          <div key={type} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span>{formulaLabel(type)}</span>
              <span>{count}</span>
            </div>
            <div style={barContainer}>
              <div style={barStyle(count, formulaMax, FORMULA_COLORS[i % FORMULA_COLORS.length])} />
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3>Rules Directory</h3>
        <p style={{ fontFamily: 'monospace', fontSize: 14, opacity: 0.8 }}>
          {stats.rules_dir || 'Not configured'}
        </p>
        <button className="btn-primary" onClick={onReload} style={{ marginTop: 12 }}>
          Reload Rules
        </button>
        <p style={{ fontSize: 12, opacity: 0.5, marginTop: 8 }}>
          Reloading will reset any in-memory modifications
        </p>
      </div>
    </div>
  )
}
