import { useState, useCallback, useMemo } from 'react'
import type { Rule, Formula, TestResult } from '../types'
import { fmtMoney, formulaLabel, regulationLabel } from '../utils/formatters'

interface Props {
  rules: Rule[]
}

type Mode = 'existing' | 'adhoc'

type HistorySortColumn = 'index' | 'mode' | 'rule' | 'margin' | 'mv' | 'qty' | 'security' | 'side'
type HistorySortDir = 'asc' | 'desc'

function HistorySortHeader({ label, column, current, dir, onSort, style }: {
  label: string; column: HistorySortColumn; current: HistorySortColumn; dir: HistorySortDir;
  onSort: (c: HistorySortColumn) => void; style?: React.CSSProperties
}) {
  const active = current === column
  return (
    <th
      style={{ ...style, cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap', position: 'sticky' as const, top: 0, zIndex: 2, background: 'var(--bg-secondary)' }}
      onClick={() => onSort(column)}
    >
      {label} <span style={{ opacity: active ? 1 : 0.3, fontSize: 10 }}>{active ? (dir === 'asc' ? '\u25B2' : '\u25BC') : '\u25B4'}</span>
    </th>
  )
}

const FORMULA_TYPES = [
  'percentage_of_market',
  'percentage_of_par',
  'greater_of',
  'fixed_amount',
  'per_share',
  'per_contract',
  'premium_plus_percentage',
  'premium_plus_underlying',
  'strategy_net_debit',
  'strategy_max_loss',
  'strategy_max_risk',
  'strategy_risk_based',
  'aggregate_debit',
  'aggregate_exercise',
  'net_capital_percentage',
  'haircut',
  'notional_percentage',
  'tiered_percentage',
] as const

const SECURITY_TYPES = ['equity', 'option', 'corporate_bond', 'municipal_bond', 'us_treasury', 'etf'] as const
const POSITION_SIDES = ['long', 'short'] as const
const OPTION_TYPES = ['none', 'call', 'put'] as const

interface ContextFields {
  market_value: number
  quantity: number
  trade_value: number
  market_price: number
  par_value: number
  underlying_price: number
  strike: number
  multiplier: number
  security_type: string
  position_side: string
  option_type: string
}

interface FormulaFields {
  type: string
  rate: number
  amount: number
  underlying_pct: number
  otm_deduction: boolean
  minimum_underlying_pct: number
  minimum_per_contract: number
}

interface HistoryEntry {
  index: number
  mode: Mode
  ruleId: string | null
  formula: FormulaFields | null
  context: ContextFields
  result: TestResult
}

const DEFAULT_CONTEXT: ContextFields = {
  market_value: 17500,
  quantity: 100,
  trade_value: 15000,
  market_price: 175,
  par_value: 1000,
  underlying_price: 175,
  strike: 0,
  multiplier: 100,
  security_type: 'equity',
  position_side: 'long',
  option_type: 'none',
}

const DEFAULT_FORMULA: FormulaFields = {
  type: 'percentage_of_market',
  rate: 0.5,
  amount: 0,
  underlying_pct: 0,
  otm_deduction: false,
  minimum_underlying_pct: 0,
  minimum_per_contract: 0,
}

export function FormulaTester({ rules }: Props) {
  const [mode, setMode] = useState<Mode>('existing')
  const [selectedRuleId, setSelectedRuleId] = useState('')
  const [ruleSearch, setRuleSearch] = useState('')
  const [context, setContext] = useState<ContextFields>({ ...DEFAULT_CONTEXT })
  const [formula, setFormula] = useState<FormulaFields>({ ...DEFAULT_FORMULA })
  const [result, setResult] = useState<TestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historySearch, setHistorySearch] = useState('')
  const [historySortCol, setHistorySortCol] = useState<HistorySortColumn>('index')
  const [historySortDir, setHistorySortDir] = useState<HistorySortDir>('desc')

  const handleHistorySort = useCallback((col: HistorySortColumn) => {
    if (col === historySortCol) {
      setHistorySortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setHistorySortCol(col)
      setHistorySortDir('asc')
    }
  }, [historySortCol])

  const getHistoryRuleLabel = useCallback((entry: HistoryEntry) => {
    return entry.ruleId ?? (entry.formula ? formulaLabel(entry.formula.type) : '-')
  }, [])

  const filteredHistory = useMemo(() => {
    if (!historySearch) return history
    const s = historySearch.toLowerCase()
    return history.filter(entry => {
      return (
        String(entry.index).includes(s) ||
        entry.mode.toLowerCase().includes(s) ||
        getHistoryRuleLabel(entry).toLowerCase().includes(s) ||
        (entry.result.margin_float != null ? fmtMoney(entry.result.margin_float).toLowerCase().includes(s) : false) ||
        (entry.result.error ? 'error'.includes(s) : false) ||
        fmtMoney(entry.context.market_value).toLowerCase().includes(s) ||
        String(entry.context.quantity).includes(s) ||
        entry.context.security_type.toLowerCase().includes(s) ||
        entry.context.position_side.toLowerCase().includes(s)
      )
    })
  }, [history, historySearch, getHistoryRuleLabel])

  const sortedHistory = useMemo(() => {
    const rows = [...filteredHistory]
    const dir = historySortDir === 'asc' ? 1 : -1
    const cmp = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: 'base' })
    rows.sort((a, b) => {
      switch (historySortCol) {
        case 'index': return dir * (a.index - b.index)
        case 'mode': return dir * cmp(a.mode, b.mode)
        case 'rule': return dir * cmp(getHistoryRuleLabel(a), getHistoryRuleLabel(b))
        case 'margin': return dir * ((a.result.margin_float ?? 0) - (b.result.margin_float ?? 0))
        case 'mv': return dir * (a.context.market_value - b.context.market_value)
        case 'qty': return dir * (a.context.quantity - b.context.quantity)
        case 'security': return dir * cmp(a.context.security_type, b.context.security_type)
        case 'side': return dir * cmp(a.context.position_side, b.context.position_side)
        default: return 0
      }
    })
    return rows
  }, [filteredHistory, historySortCol, historySortDir, getHistoryRuleLabel])

  const selectedRule = useMemo(
    () => rules.find(r => r.id === selectedRuleId) ?? null,
    [rules, selectedRuleId],
  )

  const filteredRules = useMemo(() => {
    if (!ruleSearch) return rules
    const q = ruleSearch.toLowerCase()
    return rules.filter(
      r => r.id.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
    )
  }, [rules, ruleSearch])

  const updateContext = useCallback(
    (field: keyof ContextFields, value: string | number) => {
      setContext(prev => ({ ...prev, [field]: value }))
    },
    [],
  )

  const updateFormula = useCallback(
    (field: keyof FormulaFields, value: string | number | boolean) => {
      setFormula(prev => ({ ...prev, [field]: value }))
    },
    [],
  )

  const buildContextPayload = useCallback((): Record<string, string | number> => {
    const payload: Record<string, string | number> = {}
    for (const [key, val] of Object.entries(context)) {
      if (typeof val === 'number' && val !== 0) {
        payload[key] = val
      } else if (typeof val === 'string' && val !== '' && val !== 'none') {
        payload[key] = val
      }
    }
    return payload
  }, [context])

  const buildFormulaPayload = useCallback((): Record<string, unknown> => {
    const payload: Record<string, unknown> = { type: formula.type }
    if (formula.rate) payload.rate = formula.rate
    if (formula.amount) payload.amount = formula.amount
    if (formula.underlying_pct) payload.underlying_pct = formula.underlying_pct
    if (formula.otm_deduction) payload.otm_deduction = formula.otm_deduction
    if (formula.minimum_underlying_pct) payload.minimum_underlying_pct = formula.minimum_underlying_pct
    if (formula.minimum_per_contract) payload.minimum_per_contract = formula.minimum_per_contract
    return payload
  }, [formula])

  const handleCalculate = useCallback(async () => {
    setLoading(true)
    setResult(null)

    const contextPayload = buildContextPayload()
    let body: Record<string, unknown>

    if (mode === 'existing') {
      if (!selectedRuleId) {
        setLoading(false)
        return
      }
      body = { rule_id: selectedRuleId, context: contextPayload }
    } else {
      body = { formula: buildFormulaPayload(), context: contextPayload }
    }

    try {
      const res = await fetch('/api/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data: TestResult = await res.json()
      setResult(data)

      setHistory(prev => {
        const entry: HistoryEntry = {
          index: (prev[0]?.index ?? 0) + 1,
          mode,
          ruleId: mode === 'existing' ? selectedRuleId : null,
          formula: mode === 'adhoc' ? { ...formula } : null,
          context: { ...context },
          result: data,
        }
        return [entry, ...prev].slice(0, 10)
      })
    } catch (err) {
      const errorResult: TestResult = {
        margin: null,
        margin_float: null,
        rule_id: mode === 'existing' ? selectedRuleId : 'ad-hoc',
        formula_type: mode === 'adhoc' ? formula.type : null,
        context_used: {},
        error: err instanceof Error ? err.message : 'Network error',
      }
      setResult(errorResult)
    } finally {
      setLoading(false)
    }
  }, [mode, selectedRuleId, formula, context, buildContextPayload, buildFormulaPayload])

  const restoreFromHistory = useCallback((entry: HistoryEntry) => {
    setMode(entry.mode)
    setContext({ ...entry.context })
    if (entry.mode === 'existing' && entry.ruleId) {
      setSelectedRuleId(entry.ruleId)
    } else if (entry.mode === 'adhoc' && entry.formula) {
      setFormula({ ...entry.formula })
    }
    setResult(entry.result)
  }, [])

  const renderFormulaInfo = (f: Formula | null) => {
    if (!f) return <span className="detail">No formula defined</span>
    return (
      <div className="condition-tags" style={{ marginTop: 8 }}>
        <span className="condition-tag">type: {f.type}</span>
        {f.rate > 0 && <span className="condition-tag">rate: {f.rate}</span>}
        {f.amount > 0 && <span className="condition-tag">amount: {f.amount}</span>}
        {f.underlying_pct > 0 && <span className="condition-tag">underlying_pct: {f.underlying_pct}</span>}
        {f.otm_deduction && <span className="condition-tag">otm_deduction</span>}
        {f.minimum_underlying_pct > 0 && (
          <span className="condition-tag">min_underlying_pct: {f.minimum_underlying_pct}</span>
        )}
        {f.minimum_per_contract > 0 && (
          <span className="condition-tag">min_per_contract: {f.minimum_per_contract}</span>
        )}
        {f.floor_rate > 0 && <span className="condition-tag">floor_rate: {f.floor_rate}</span>}
        {f.per_contract_minimum > 0 && (
          <span className="condition-tag">per_contract_min: {f.per_contract_minimum}</span>
        )}
        {f.calculation && <span className="condition-tag">calc: {f.calculation}</span>}
      </div>
    )
  }

  return (
    <div>
      {/* Mode toggle */}
      <div className="panel">
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button
            className={mode === 'existing' ? 'btn-primary' : 'btn-secondary'}
            onClick={() => setMode('existing')}
          >
            Test Existing Rule
          </button>
          <button
            className={mode === 'adhoc' ? 'btn-primary' : 'btn-secondary'}
            onClick={() => setMode('adhoc')}
          >
            Ad-Hoc Formula
          </button>
        </div>

        {/* Existing Rule mode */}
        {mode === 'existing' && (
          <div style={{ marginBottom: 16 }}>
            <h3>Select Rule</h3>
            <div className="form-group">
              <label>Search rules</label>
              <input
                type="text"
                className="search-input"
                placeholder="Filter by ID or description..."
                value={ruleSearch}
                onChange={e => setRuleSearch(e.target.value)}
                style={{ width: '100%', marginBottom: 8 }}
              />
            </div>
            <div className="form-group">
              <label>Rule</label>
              <select
                value={selectedRuleId}
                onChange={e => setSelectedRuleId(e.target.value)}
                style={{ width: '100%' }}
              >
                <option value="">-- Select a rule --</option>
                {filteredRules.map(r => (
                  <option key={r.id} value={r.id}>
                    {r.id} - {r.description}
                  </option>
                ))}
              </select>
            </div>
            {selectedRule && (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                  <span className="badge badge-blue">{regulationLabel(selectedRule.regulation)}</span>
                  <span className="detail">{selectedRule.citation}</span>
                </div>
                <div className="detail" style={{ marginBottom: 4 }}>{selectedRule.description}</div>
                {renderFormulaInfo(selectedRule.formula)}
              </div>
            )}
          </div>
        )}

        {/* Ad-Hoc Formula mode */}
        {mode === 'adhoc' && (
          <div style={{ marginBottom: 16 }}>
            <h3>Build Formula</h3>
            <div className="form-row">
              <div className="form-group">
                <label>Formula Type</label>
                <select
                  value={formula.type}
                  onChange={e => updateFormula('type', e.target.value)}
                  style={{ width: '100%' }}
                >
                  {FORMULA_TYPES.map(t => (
                    <option key={t} value={t}>{formulaLabel(t)}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Rate</label>
                <input
                  type="number"
                  step="0.01"
                  value={formula.rate}
                  onChange={e => updateFormula('rate', parseFloat(e.target.value) || 0)}
                  style={{ width: '100%' }}
                />
              </div>
              <div className="form-group">
                <label>Amount</label>
                <input
                  type="number"
                  step="0.01"
                  value={formula.amount}
                  onChange={e => updateFormula('amount', parseFloat(e.target.value) || 0)}
                  style={{ width: '100%' }}
                />
              </div>
              <div className="form-group">
                <label>Underlying %</label>
                <input
                  type="number"
                  step="0.01"
                  value={formula.underlying_pct}
                  onChange={e => updateFormula('underlying_pct', parseFloat(e.target.value) || 0)}
                  style={{ width: '100%' }}
                />
              </div>
              <div className="form-group">
                <label>OTM Deduction</label>
                <select
                  value={formula.otm_deduction ? 'true' : 'false'}
                  onChange={e => updateFormula('otm_deduction', e.target.value === 'true')}
                  style={{ width: '100%' }}
                >
                  <option value="false">No</option>
                  <option value="true">Yes</option>
                </select>
              </div>
              <div className="form-group">
                <label>Min Underlying %</label>
                <input
                  type="number"
                  step="0.01"
                  value={formula.minimum_underlying_pct}
                  onChange={e => updateFormula('minimum_underlying_pct', parseFloat(e.target.value) || 0)}
                  style={{ width: '100%' }}
                />
              </div>
              <div className="form-group">
                <label>Min Per Contract</label>
                <input
                  type="number"
                  step="0.01"
                  value={formula.minimum_per_contract}
                  onChange={e => updateFormula('minimum_per_contract', parseFloat(e.target.value) || 0)}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Context fields */}
        <h3>Position Context</h3>
        <div className="form-row">
          <div className="form-group">
            <label>market_value</label>
            <input
              type="number"
              value={context.market_value}
              onChange={e => updateContext('market_value', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>quantity</label>
            <input
              type="number"
              value={context.quantity}
              onChange={e => updateContext('quantity', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>trade_value</label>
            <input
              type="number"
              value={context.trade_value}
              onChange={e => updateContext('trade_value', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>market_price</label>
            <input
              type="number"
              value={context.market_price}
              onChange={e => updateContext('market_price', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>par_value</label>
            <input
              type="number"
              value={context.par_value}
              onChange={e => updateContext('par_value', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>underlying_price</label>
            <input
              type="number"
              value={context.underlying_price}
              onChange={e => updateContext('underlying_price', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>strike</label>
            <input
              type="number"
              value={context.strike}
              onChange={e => updateContext('strike', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>multiplier</label>
            <input
              type="number"
              value={context.multiplier}
              onChange={e => updateContext('multiplier', parseFloat(e.target.value) || 0)}
              style={{ width: '100%' }}
            />
          </div>
          <div className="form-group">
            <label>security_type</label>
            <select
              value={context.security_type}
              onChange={e => updateContext('security_type', e.target.value)}
              style={{ width: '100%' }}
            >
              {SECURITY_TYPES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>position_side</label>
            <select
              value={context.position_side}
              onChange={e => updateContext('position_side', e.target.value)}
              style={{ width: '100%' }}
            >
              {POSITION_SIDES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>option_type</label>
            <select
              value={context.option_type}
              onChange={e => updateContext('option_type', e.target.value)}
              style={{ width: '100%' }}
            >
              {OPTION_TYPES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Calculate button */}
        <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
          <button
            className="btn-primary"
            onClick={handleCalculate}
            disabled={loading || (mode === 'existing' && !selectedRuleId)}
          >
            {loading ? 'Calculating...' : 'Calculate Margin'}
          </button>
          <button
            className="btn-secondary"
            onClick={() => {
              setContext({ ...DEFAULT_CONTEXT })
              setFormula({ ...DEFAULT_FORMULA })
              setSelectedRuleId('')
              setRuleSearch('')
              setResult(null)
            }}
          >
            Reset
          </button>
        </div>

        {/* Result display */}
        {result && (
          <div className="result-box">
            <div className={`margin-value${result.error ? ' error' : ''}`}>
              {result.error
                ? 'Error'
                : result.margin_float != null
                  ? fmtMoney(result.margin_float)
                  : result.margin ?? '-'}
            </div>
            {result.error && (
              <div className="detail" style={{ color: 'var(--accent-red)', marginTop: 4 }}>
                {result.error}
              </div>
            )}
            <div className="detail" style={{ marginTop: 8 }}>
              <strong>Rule:</strong> {result.rule_id}
              {result.formula_type && (
                <>
                  {' | '}
                  <strong>Formula:</strong>{' '}
                  <span className="badge badge-blue">{formulaLabel(result.formula_type)}</span>
                </>
              )}
            </div>
            {Object.keys(result.context_used).length > 0 && (
              <div className="detail" style={{ marginTop: 8 }}>
                <strong>Context used:</strong>
                <div className="condition-tags" style={{ marginTop: 4 }}>
                  {Object.entries(result.context_used).map(([k, v]) => (
                    <span key={k} className="condition-tag">
                      {k}: {v}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* History table */}
      {history.length > 0 && (
        <div className="table-section">
          <div className="table-toolbar">
            <h2>Test History</h2>
            <button className="btn-secondary btn-sm" onClick={() => setHistory([])}>
              Clear
            </button>
          </div>
          <div style={{ display: 'flex', gap: 12, padding: '0 16px 16px', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Search history..."
              value={historySearch}
              onChange={e => setHistorySearch(e.target.value)}
              style={{ width: 320 }}
            />
            {historySearch && (
              <button className="btn-secondary btn-sm" onClick={() => setHistorySearch('')}>Clear</button>
            )}
            <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
              {sortedHistory.length} of {history.length} entries
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <HistorySortHeader label="#" column="index" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="Mode" column="mode" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="Rule / Formula" column="rule" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="Margin" column="margin" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="MV" column="mv" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="Qty" column="qty" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="Security" column="security" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
                <HistorySortHeader label="Side" column="side" current={historySortCol} dir={historySortDir} onSort={handleHistorySort} />
              </tr>
            </thead>
            <tbody>
              {sortedHistory.map(entry => (
                <tr
                  key={entry.index}
                  className="clickable"
                  onClick={() => restoreFromHistory(entry)}
                >
                  <td className="mono">{entry.index}</td>
                  <td>
                    <span className={`badge ${entry.mode === 'existing' ? 'badge-green' : 'badge-amber'}`}>
                      {entry.mode === 'existing' ? 'Rule' : 'Ad-Hoc'}
                    </span>
                  </td>
                  <td className="truncate">
                    {entry.ruleId ?? (entry.formula ? formulaLabel(entry.formula.type) : '-')}
                  </td>
                  <td className="mono right">
                    {entry.result.error ? (
                      <span style={{ color: 'var(--accent-red)' }}>Error</span>
                    ) : (
                      fmtMoney(entry.result.margin_float)
                    )}
                  </td>
                  <td className="mono right">{fmtMoney(entry.context.market_value)}</td>
                  <td className="mono right">{entry.context.quantity}</td>
                  <td>{entry.context.security_type}</td>
                  <td>{entry.context.position_side}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
