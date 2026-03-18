import { useState, useMemo, useCallback } from 'react'
import type { Rule, Formula, Minimum } from '../types'
import { formulaLabel, ruleIdLabel, regulationLabel, regulationBadge, fmtPct } from '../utils/formatters'

interface Props {
  rules: Rule[]
  loading: boolean
  onRuleUpdated: () => void
}

type SortColumn = 'id' | 'regulation' | 'asset_class' | 'formula_type' | 'rate' | 'description' | 'citation' | 'status'
type SortDir = 'asc' | 'desc' | null

const FORMULA_TYPE_OPTIONS = [
  'percentage_of_market_value',
  'percentage_of_trade_value',
  'percentage_of_principal',
  'fixed_per_share',
  'full_payment',
  'good_faith',
  'naked_option',
  'debit_spread',
  'credit_spread',
  'short_straddle_strangle',
  'iron_condor',
  'covered_equity',
  'protective_equity',
  'conversion',
  'spread_max_loss',
  'box_spread',
  'ratio_spread',
  'synthetic_stock',
] as const

const STATUS_BADGE: Record<string, string> = {
  active: 'badge-green',
  not_implemented: 'badge-amber',
  informational: 'badge-muted',
}

const ASSET_CLASS_BADGE: Record<string, string> = {
  Equity: 'badge-green',
  Option: 'badge-purple',
  'Corporate Bond': 'badge-amber',
  Bond: 'badge-amber',
  'Municipal Bond': 'badge-amber',
  'US Treasury': 'badge-blue',
  'Agency Debt': 'badge-blue',
  ETF: 'badge-cyan',
  ETP: 'badge-cyan',
}

/** Fields relevant to each formula type. */
const FORMULA_FIELDS_BY_TYPE: Record<string, (keyof Formula)[]> = {
  percentage_of_market_value: ['rate'],
  percentage_of_trade_value: ['rate'],
  percentage_of_principal: ['rate'],
  fixed_per_share: ['amount'],
  full_payment: [],
  good_faith: ['rate'],
  naked_option: ['premium_pct', 'underlying_pct', 'otm_deduction', 'minimum_underlying_pct', 'minimum_per_contract'],
  debit_spread: [],
  credit_spread: ['rate', 'multiplier'],
  short_straddle_strangle: ['rate', 'multiplier'],
  iron_condor: ['rate', 'multiplier'],
  covered_equity: ['rate'],
  protective_equity: ['rate'],
  conversion: ['rate'],
  spread_max_loss: ['multiplier'],
  box_spread: ['rate', 'floor_rate'],
  ratio_spread: ['rate', 'multiplier', 'per_contract_minimum'],
  synthetic_stock: ['rate'],
}

const ALL_EDITABLE_FORMULA_FIELDS: (keyof Formula)[] = [
  'rate', 'amount', 'underlying_pct', 'otm_deduction',
  'minimum_underlying_pct', 'minimum_per_contract', 'multiplier',
  'floor_rate', 'per_contract_minimum', 'premium_pct',
]

function statusLabel(status: string): string {
  return status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formulaFieldLabel(field: keyof Formula): string {
  const labels: Partial<Record<keyof Formula, string>> = {
    rate: 'Rate', amount: 'Amount', premium_pct: 'Premium %',
    underlying_pct: 'Underlying %', otm_deduction: 'OTM Deduction',
    minimum_underlying_pct: 'Min Underlying %', minimum_per_contract: 'Min Per Contract',
    multiplier: 'Multiplier', floor_rate: 'Floor Rate', per_contract_minimum: 'Per Contract Minimum',
  }
  return labels[field] ?? String(field).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function getEditableFormulaFields(formulaType: string): (keyof Formula)[] {
  return FORMULA_FIELDS_BY_TYPE[formulaType] ?? ALL_EDITABLE_FORMULA_FIELDS
}

// --- Column definitions ---

interface ColumnDef {
  key: SortColumn
  label: string
  filterType: 'text' | 'select'
}

const COLUMNS: ColumnDef[] = [
  { key: 'id', label: 'ID', filterType: 'text' },
  { key: 'regulation', label: 'Regulation', filterType: 'select' },
  { key: 'asset_class', label: 'Asset Class', filterType: 'select' },
  { key: 'formula_type', label: 'Formula Type', filterType: 'select' },
  { key: 'rate', label: 'Rate', filterType: 'text' },
  { key: 'description', label: 'Description', filterType: 'text' },
  { key: 'citation', label: 'Citation', filterType: 'text' },
  { key: 'status', label: 'Status', filterType: 'select' },
]

function getColumnValue(rule: Rule, col: SortColumn): string {
  switch (col) {
    case 'id': return rule.id
    case 'regulation': return rule.regulation
    case 'asset_class': return rule.asset_class
    case 'formula_type': return rule.formula?.type ?? ''
    case 'rate': return rule.formula && rule.formula.rate > 0 ? fmtPct(rule.formula.rate) : ''
    case 'description': return rule.description
    case 'citation': return rule.citation
    case 'status': return rule.calculation_status
  }
}

function getSortValue(rule: Rule, col: SortColumn): string | number {
  if (col === 'rate') return rule.formula?.rate ?? 0
  return getColumnValue(rule, col)
}

export function RulesBrowser({ rules, loading, onRuleUpdated }: Props) {
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [sortCol, setSortCol] = useState<SortColumn | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [editingRule, setEditingRule] = useState<Rule | null>(null)
  const [draft, setDraft] = useState<Rule | null>(null)
  const [saving, setSaving] = useState(false)

  // Derive unique options for select filters
  const selectOptions = useMemo(() => {
    const opts: Record<string, string[]> = {}
    const sets: Record<string, Set<string>> = {
      regulation: new Set(), asset_class: new Set(),
      formula_type: new Set(), status: new Set(),
    }
    for (const r of rules) {
      sets.regulation.add(r.regulation)
      if (r.asset_class) sets.asset_class.add(r.asset_class)
      if (r.formula?.type) sets.formula_type.add(r.formula.type)
      sets.status.add(r.calculation_status)
    }
    for (const [k, s] of Object.entries(sets)) {
      opts[k] = Array.from(s).sort()
    }
    return opts
  }, [rules])

  // Filter
  const filtered = useMemo(() => {
    return rules.filter(r => {
      for (const col of COLUMNS) {
        const f = filters[col.key]
        if (!f) continue
        const val = getColumnValue(r, col.key)
        if (col.filterType === 'select') {
          if (val !== f) return false
        } else {
          if (!val.toLowerCase().includes(f.toLowerCase())) return false
        }
      }
      return true
    })
  }, [rules, filters])

  // Sort
  const sorted = useMemo(() => {
    if (!sortCol || !sortDir) return filtered
    const dir = sortDir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const va = getSortValue(a, sortCol)
      const vb = getSortValue(b, sortCol)
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
      return String(va).localeCompare(String(vb)) * dir
    })
  }, [filtered, sortCol, sortDir])

  const onHeaderClick = useCallback((col: SortColumn) => {
    if (sortCol !== col) { setSortCol(col); setSortDir('asc') }
    else if (sortDir === 'asc') setSortDir('desc')
    else { setSortCol(null); setSortDir(null) }
  }, [sortCol, sortDir])

  const sortIndicator = (col: SortColumn) => {
    if (sortCol !== col || !sortDir) return ''
    return sortDir === 'asc' ? ' \u25B2' : ' \u25BC'
  }

  const setFilter = useCallback((key: string, value: string) => {
    setFilters(prev => {
      const next = { ...prev }
      if (value) next[key] = value
      else delete next[key]
      return next
    })
  }, [])

  const hasActiveFilters = Object.keys(filters).length > 0

  // Drawer open/close
  const openEditor = useCallback((rule: Rule) => {
    setEditingRule(rule)
    setDraft(structuredClone(rule))
  }, [])

  const closeEditor = useCallback(() => {
    setEditingRule(null)
    setDraft(null)
  }, [])

  // Draft mutation helpers
  const updateDraftField = useCallback(<K extends keyof Rule>(field: K, value: Rule[K]) => {
    setDraft(prev => prev ? { ...prev, [field]: value } : prev)
  }, [])

  const updateFormulaField = useCallback(<K extends keyof Formula>(field: K, value: Formula[K]) => {
    setDraft(prev => {
      if (!prev) return prev
      const formula = prev.formula ? { ...prev.formula, [field]: value } : null
      return { ...prev, formula }
    })
  }, [])

  const updateMinimumField = useCallback(<K extends keyof Minimum>(field: K, value: Minimum[K]) => {
    setDraft(prev => {
      if (!prev) return prev
      const minimum = prev.minimum ? { ...prev.minimum, [field]: value } : { type: 'fixed', amount: 0, [field]: value }
      return { ...prev, minimum }
    })
  }, [])

  const handleSave = useCallback(async () => {
    if (!draft) return
    setSaving(true)
    try {
      const res = await fetch(`/api/rules/${draft.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: draft.description,
          formula: draft.formula,
          minimum: draft.minimum,
          conditions: draft.conditions,
        }),
      })
      if (!res.ok) throw new Error(await res.text() || `Save failed (${res.status})`)
      closeEditor()
      onRuleUpdated()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to save rule')
    } finally {
      setSaving(false)
    }
  }, [draft, closeEditor, onRuleUpdated])

  // Render helpers
  const renderFormulaEditor = () => {
    if (!draft?.formula) return <p style={{ color: 'var(--text-muted)' }}>No formula defined for this rule.</p>
    const fields = getEditableFormulaFields(draft.formula.type)
    return (
      <>
        <div className="form-group">
          <label>Formula Type</label>
          <select value={draft.formula.type} onChange={e => updateFormulaField('type', e.target.value)}>
            {FORMULA_TYPE_OPTIONS.map(t => <option key={t} value={t}>{formulaLabel(t)}</option>)}
          </select>
        </div>
        {fields.map(field => {
          if (field === 'otm_deduction') {
            return (
              <div className="form-group" key={field}>
                <label>
                  <input type="checkbox" checked={draft.formula!.otm_deduction}
                    onChange={e => updateFormulaField('otm_deduction', e.target.checked)} />{' '}
                  OTM Deduction
                </label>
              </div>
            )
          }
          const val = draft.formula![field]
          if (typeof val !== 'number') return null
          return (
            <div className="form-group" key={field}>
              <label>{formulaFieldLabel(field)}</label>
              <input type="number" step="any" value={val}
                onChange={e => updateFormulaField(field, parseFloat(e.target.value) || 0)} />
            </div>
          )
        })}
      </>
    )
  }

  const renderConditions = () => {
    if (!draft) return null
    const entries = Object.entries(draft.conditions)
    if (entries.length === 0) return <p style={{ color: 'var(--text-muted)' }}>No conditions.</p>
    return (
      <div className="condition-tags">
        {entries.map(([key, val]) => (
          <span key={key} className="condition-tag">
            {key}: {typeof val === 'object' ? JSON.stringify(val) : String(val)}
          </span>
        ))}
      </div>
    )
  }

  // Cell renderer
  const renderCell = (rule: Rule, col: SortColumn) => {
    switch (col) {
      case 'id':
        return <td key={col}>{ruleIdLabel(rule.id)}</td>
      case 'regulation':
        return (
          <td key={col}>
            <span className={`badge ${regulationBadge(rule.regulation)}`}>
              {regulationLabel(rule.regulation)}
            </span>
          </td>
        )
      case 'asset_class':
        return (
          <td key={col}>
            {rule.asset_class ? (
              <span className={`badge ${ASSET_CLASS_BADGE[rule.asset_class] ?? 'badge-muted'}`}>
                {rule.asset_class}
              </span>
            ) : (
              <span style={{ color: 'var(--text-muted)' }}>-</span>
            )}
          </td>
        )
      case 'formula_type':
        return (
          <td key={col}>
            {rule.formula?.type ? (
              <span className="badge badge-cyan">{formulaLabel(rule.formula.type)}</span>
            ) : (
              <span className="badge badge-muted">None</span>
            )}
          </td>
        )
      case 'rate':
        return (
          <td key={col} className="mono right">
            {rule.formula && rule.formula.rate > 0 ? fmtPct(rule.formula.rate) : '-'}
          </td>
        )
      case 'description':
        return <td key={col} className="truncate">{rule.description}</td>
      case 'citation':
        return <td key={col}>{rule.citation}</td>
      case 'status':
        return (
          <td key={col}>
            <span className={`badge ${STATUS_BADGE[rule.calculation_status] ?? 'badge-muted'}`}>
              {statusLabel(rule.calculation_status)}
            </span>
          </td>
        )
    }
  }

  return (
    <>
      {/* Toolbar */}
      <div className="table-toolbar">
        <h2>Rules</h2>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          {sorted.length} / {rules.length} rules
        </span>
        {hasActiveFilters && (
          <button className="btn-secondary btn-sm" onClick={() => setFilters({})}>
            Clear Filters
          </button>
        )}
      </div>

      {/* Table */}
      <div className="table-section">
        {loading ? (
          <p style={{ color: 'var(--text-muted)', padding: '2rem', textAlign: 'center' }}>Loading rules...</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                {/* Sort headers */}
                <tr>
                  {COLUMNS.map(col => (
                    <th key={col.key}
                      className={col.key === 'rate' ? 'right' : undefined}
                      style={{ position: 'sticky', top: 0, zIndex: 2, background: 'var(--bg-secondary)' }}
                      onClick={() => onHeaderClick(col.key)}>
                      {col.label}
                      <span className="sort-indicator">{sortIndicator(col.key)}</span>
                    </th>
                  ))}
                </tr>
                {/* Filter row */}
                <tr>
                  {COLUMNS.map(col => (
                    <th key={`f-${col.key}`} style={{ padding: '4px 8px', background: 'var(--bg-card)', position: 'sticky', top: 37, zIndex: 2 }}>
                      {col.filterType === 'select' ? (
                        <select
                          value={filters[col.key] ?? ''}
                          onChange={e => setFilter(col.key, e.target.value)}
                          style={{ width: '100%', fontSize: 11, padding: '3px 6px' }}
                        >
                          <option value="">All</option>
                          {(selectOptions[col.key] ?? []).map(v => (
                            <option key={v} value={v}>
                              {col.key === 'regulation' ? regulationLabel(v)
                                : col.key === 'formula_type' ? formulaLabel(v)
                                : col.key === 'status' ? statusLabel(v)
                                : v}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          placeholder="Filter..."
                          value={filters[col.key] ?? ''}
                          onChange={e => setFilter(col.key, e.target.value)}
                          style={{ width: '100%', fontSize: 11, padding: '3px 6px' }}
                        />
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map(rule => (
                  <tr key={rule.id} className="clickable" onClick={() => openEditor(rule)}>
                    {COLUMNS.map(col => renderCell(rule, col.key))}
                  </tr>
                ))}
                {sorted.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                      {rules.length === 0 ? 'No rules loaded.' : 'No rules match the current filters.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Rule Editor Drawer */}
      {editingRule && draft && (
        <>
          <div className="drawer-overlay" onClick={closeEditor} />
          <div className="drawer">
            <div className="drawer-header">
              <h2>{ruleIdLabel(draft.id)}</h2>
              <button className="btn-secondary" onClick={closeEditor} aria-label="Close">&times;</button>
            </div>

            <div className="drawer-body">
              {/* Info Section */}
              <section className="panel">
                <h3>Info</h3>
                <div className="form-row">
                  <div className="form-group">
                    <label>ID</label>
                    <span style={{ fontSize: 12 }}>{ruleIdLabel(draft.id)}</span>
                  </div>
                  <div className="form-group">
                    <label>Regulation</label>
                    <span className={`badge ${regulationBadge(draft.regulation)}`}>
                      {regulationLabel(draft.regulation)}
                    </span>
                  </div>
                  <div className="form-group">
                    <label>Asset Class</label>
                    {draft.asset_class ? (
                      <span className={`badge ${ASSET_CLASS_BADGE[draft.asset_class] ?? 'badge-muted'}`}>
                        {draft.asset_class}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>-</span>
                    )}
                  </div>
                </div>
                <div className="form-group">
                  <label>Citation</label>
                  <span>{draft.citation}</span>
                </div>
                {draft.source_quote && (
                  <div className="form-group">
                    <label>Source Quote</label>
                    <blockquote style={{ margin: 0, paddingLeft: '0.75rem', borderLeft: '3px solid var(--accent-blue)', opacity: 0.85, fontSize: 12 }}>
                      {draft.source_quote}
                    </blockquote>
                  </div>
                )}
              </section>

              {/* Formula Editor */}
              <section className="panel">
                <h3>Formula</h3>
                {renderFormulaEditor()}
              </section>

              {/* Minimum */}
              <section className="panel">
                <h3>Minimum</h3>
                {draft.minimum ? (
                  <div className="form-row">
                    <div className="form-group">
                      <label>Type</label>
                      <select value={draft.minimum.type} onChange={e => updateMinimumField('type', e.target.value)}>
                        <option value="fixed">Fixed</option>
                        <option value="per_contract">Per Contract</option>
                        <option value="per_share">Per Share</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <label>Amount</label>
                      <input type="number" step="any" value={draft.minimum.amount}
                        onChange={e => updateMinimumField('amount', parseFloat(e.target.value) || 0)} />
                    </div>
                  </div>
                ) : (
                  <p style={{ color: 'var(--text-muted)' }}>No minimum defined.</p>
                )}
              </section>

              {/* Conditions */}
              <section className="panel">
                <h3>Conditions</h3>
                {renderConditions()}
              </section>

              {/* Description */}
              <section className="panel">
                <h3>Description</h3>
                <div className="form-group">
                  <textarea rows={4} value={draft.description}
                    onChange={e => updateDraftField('description', e.target.value)} />
                </div>
              </section>
            </div>

            <div className="drawer-footer">
              <button className="btn-secondary" onClick={closeEditor} disabled={saving}>Cancel</button>
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
