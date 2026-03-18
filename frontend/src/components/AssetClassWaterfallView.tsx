import { useState, useEffect, useMemo, Fragment } from 'react'
import { RegulatoryTimeline } from './RegulatoryTimeline'

interface WaterfallRule {
  rule_id: string
  name: string
  section: string
  position_side?: string
  formula_type: string
  formula_detail: string
  reg_t_initial?: string
  finra_maintenance?: string
  leverage_factor?: number
  base_rate?: number
  stress_range?: string
  scenarios?: number
  conditions: string[]
  definition: string
}

interface WaterfallCategory {
  priority: number
  name: string
  rationale: string
  citation: string
  rules: WaterfallRule[]
}

interface WaterfallData {
  categories: WaterfallCategory[]
}

const priorityColors: Record<number, string> = {
  1: '#ef4444', 2: '#f97316', 3: '#f59e0b', 4: '#14b8a6',
  5: '#3b82f6', 6: '#6366f1', 7: '#8b5cf6', 8: '#a78bfa',
  9: '#ec4899', 10: '#06b6d4', 11: '#64748b', 12: '#dc2626',
}

const assetClassLabels: Record<string, string> = {
  'equity': 'Equity',
  'fixed-income': 'Fixed Income',
  'etf': 'ETF / ETP',
  'concentrated': 'Concentrated',
  'day-trading': 'Day Trading',
  'portfolio-margin': 'Portfolio Margin',
  'reg-t-equity': 'Reg T: Equity',
  'reg-t-fixed-income': 'Reg T: Fixed Income',
  'reg-t-options': 'Reg T: Options',
  'reg-t-special-accounts': 'Reg T: SMA & Accounts',
  'sec-15c3-1': 'SEC 15c3-1 (Net Capital)',
  'sec-15c3-3': 'SEC 15c3-3 (Customer Protection)',
}

type SortColumn = 'priority' | 'category' | 'section' | 'rule' | 'formula' | 'definition'
type SortDir = 'asc' | 'desc'

function SortHeader({ label, column, current, dir, onSort, style }: {
  label: string; column: SortColumn; current: SortColumn; dir: SortDir;
  onSort: (c: SortColumn) => void; style?: React.CSSProperties
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

export function AssetClassWaterfallView({ assetClass }: { assetClass: string }) {
  const [data, setData] = useState<WaterfallData | null>(null)
  const [expandedRule, setExpandedRule] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [timelineSection, setTimelineSection] = useState<string | null>(null)
  const [sortCol, setSortCol] = useState<SortColumn>('priority')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  useEffect(() => {
    setExpandedRule(null)
    setSearch('')
    setSortCol('priority')
    setSortDir('asc')
    fetch(`/api/waterfall/${assetClass}`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData(null))
  }, [assetClass])

  const handleSort = (col: SortColumn) => {
    if (col === sortCol) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  const categories = data?.categories || []
  const totalRules = categories.reduce((sum, c) => sum + (c.rules?.length || 0), 0)
  const mono = "'SF Mono','Fira Code','Consolas',monospace"

  const allRows = useMemo(() =>
    categories.flatMap(cat =>
      (cat.rules || []).map(rule => ({ cat, rule }))
    ), [categories])

  const filteredRows = useMemo(() =>
    allRows.filter(({ cat, rule }) => {
      if (!search) return true
      const s = search.toLowerCase()
      return (
        rule.name.toLowerCase().includes(s) ||
        rule.rule_id.toLowerCase().includes(s) ||
        rule.definition.toLowerCase().includes(s) ||
        rule.formula_detail.toLowerCase().includes(s) ||
        cat.name.toLowerCase().includes(s) ||
        cat.rationale.toLowerCase().includes(s) ||
        (cat.citation || '').toLowerCase().includes(s) ||
        (rule.section || '').toLowerCase().includes(s) ||
        (rule.formula_type || '').toLowerCase().includes(s) ||
        rule.conditions.some(c => c.toLowerCase().includes(s))
      )
    }), [allRows, search])

  const sortedRows = useMemo(() => {
    const rows = [...filteredRows]
    const cmp = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: 'base' })
    const dir = sortDir === 'asc' ? 1 : -1
    rows.sort((a, b) => {
      switch (sortCol) {
        case 'priority': return dir * (a.cat.priority - b.cat.priority)
        case 'category': return dir * cmp(a.cat.name, b.cat.name)
        case 'section': return dir * cmp(a.rule.section || '', b.rule.section || '')
        case 'rule': return dir * cmp(a.rule.name, b.rule.name)
        case 'formula': return dir * cmp(a.rule.formula_detail, b.rule.formula_detail)
        case 'definition': return dir * cmp(a.rule.definition, b.rule.definition)
        default: return 0
      }
    })
    return rows
  }, [filteredRows, sortCol, sortDir])

  if (!data) return <div style={{ padding: 24, color: 'var(--text-secondary)' }}>Loading waterfall...</div>

  const showCategorySeparators = sortCol === 'priority'
  let lastCatPriority = -1

  return (
    <div className="table-section">
      <div className="table-toolbar">
        <h2>{assetClassLabels[assetClass] || assetClass} Margin Waterfall</h2>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          {categories.length} categories, {totalRules} rules
        </span>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, padding: '0 16px 16px', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search rules, conditions, formulas..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 320 }}
        />
        {search && (
          <button className="btn-secondary btn-sm" onClick={() => setSearch('')}>Clear</button>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          {filteredRows.length} of {totalRules} rules
        </span>
      </div>

      {/* Main table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <SortHeader label="#" column="priority" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 36 }} />
              <SortHeader label="Category" column="category" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 180 }} />
              <SortHeader label="Section" column="section" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 160 }} />
              <SortHeader label="Rule" column="rule" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 220 }} />
              <SortHeader label="Formula" column="formula" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 260 }} />
              <SortHeader label="Definition" column="definition" current={sortCol} dir={sortDir} onSort={handleSort} />
            </tr>
          </thead>
          <tbody>
            {sortedRows.map(({ cat, rule }, idx) => {
              const color = priorityColors[cat.priority] || 'var(--text-secondary)'
              const ruleKey = `${cat.priority}-${rule.rule_id}`
              const isExpanded = expandedRule === ruleKey
              const isNewCategory = showCategorySeparators && cat.priority !== lastCatPriority
              if (showCategorySeparators) lastCatPriority = cat.priority
              const catRowCount = sortedRows.filter(r => r.cat.priority === cat.priority).length

              return (
                <Fragment key={ruleKey}>
                  {/* Category separator */}
                  {isNewCategory && (
                    <tr style={{ background: 'rgba(79, 143, 247, 0.06)', borderTop: `2px solid ${color}` }}>
                      <td style={{ fontWeight: 700, fontSize: 13, color, textAlign: 'center' }}>{cat.priority}</td>
                      <td colSpan={2} style={{ fontWeight: 700, fontSize: 13 }}>
                        <span style={{ borderLeft: `3px solid ${color}`, paddingLeft: 8 }}>{cat.name}</span>
                        <span style={{ marginLeft: 12, fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>
                          {catRowCount} {catRowCount === 1 ? 'rule' : 'rules'}
                        </span>
                      </td>
                      <td style={{ fontSize: 11, fontFamily: mono, color: 'var(--text-muted)' }}>{cat.citation}</td>
                      <td></td>
                      <td style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{cat.rationale}</td>
                    </tr>
                  )}

                  {/* Rule row */}
                  <tr
                    className="clickable"
                    onClick={() => setExpandedRule(isExpanded ? null : ruleKey)}
                  >
                    <td style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 11 }}>{idx + 1}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{cat.name}</span>
                      </div>
                    </td>
                    <td style={{ fontSize: 11, fontFamily: mono, color: 'var(--accent-blue)' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <span>{rule.section}</span>
                        <span
                          style={{
                            cursor: 'pointer',
                            fontSize: 9, fontWeight: 700, fontFamily: 'inherit',
                            letterSpacing: 1.2, textTransform: 'uppercase',
                            padding: '2px 6px', borderRadius: 3,
                            background: 'rgba(99, 102, 241, 0.2)',
                            color: '#a5b4fc',
                            border: '1px solid rgba(99, 102, 241, 0.35)',
                            width: 'fit-content',
                          }}
                          onClick={e => { e.stopPropagation(); setTimelineSection(rule.section || null) }}
                          title="View regulatory timeline"
                        >
                          Reg Lineage
                        </span>
                      </div>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, fontSize: 12 }}>{rule.name}</span>
                    </td>
                    <td>
                      <span style={{ fontSize: 11, fontFamily: mono, color: 'var(--accent-amber)', lineHeight: 1.4 }}>
                        {rule.formula_detail}
                      </span>
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                      {rule.definition.length > 160 && !isExpanded
                        ? rule.definition.slice(0, 160) + '...'
                        : rule.definition}
                    </td>
                  </tr>

                  {/* Expanded detail row */}
                  {isExpanded && (
                    <tr style={{ background: 'rgba(0,0,0,0.12)' }}>
                      <td></td>
                      <td colSpan={5} style={{ padding: '12px 16px' }}>
                        {/* Rule lineage */}
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 12,
                          marginBottom: 12, paddingBottom: 10,
                          borderBottom: '1px solid var(--border)',
                        }}>
                          <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: 1 }}>Lineage</div>
                          <span style={{
                            fontSize: 11, fontFamily: mono, fontWeight: 600,
                            padding: '2px 8px', borderRadius: 4,
                            background: 'rgba(99, 102, 241, 0.15)',
                            color: '#a5b4fc',
                          }}>
                            {rule.rule_id}
                          </span>
                          <span style={{
                            fontSize: 11, fontFamily: mono,
                            padding: '2px 8px', borderRadius: 4,
                            background: 'rgba(59, 130, 246, 0.12)',
                            color: 'var(--accent-blue)',
                          }}>
                            {rule.section.startsWith('220.') ? `Reg T ${rule.section}` : rule.section.startsWith('15c3-') || rule.section.startsWith('17a-') || rule.section.startsWith('Exhibit A') ? `SEC ${rule.section}` : `FINRA ${rule.section}`}
                          </span>
                          <span
                            style={{
                              cursor: 'pointer',
                              fontSize: 9, fontWeight: 700,
                              letterSpacing: 1.2, textTransform: 'uppercase',
                              padding: '2px 6px', borderRadius: 3,
                              background: 'rgba(99, 102, 241, 0.2)',
                              color: '#a5b4fc',
                              border: '1px solid rgba(99, 102, 241, 0.35)',
                            }}
                            onClick={() => setTimelineSection(rule.section || null)}
                            title="View regulatory timeline"
                          >
                            Reg Lineage
                          </span>
                          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>ParagraphReg Published Rule</span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
                          <div>
                            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: 1 }}>Conditions</div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                              {rule.conditions.map((c, i) => (
                                <div key={i} style={{ marginBottom: 2 }}>• {typeof c === 'string' ? c : JSON.stringify(c)}</div>
                              ))}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: 1 }}>Margin Rates</div>
                            <div style={{
                              fontSize: 12, fontFamily: mono, lineHeight: 1.6,
                              padding: '6px 10px', borderRadius: 4,
                              background: 'var(--bg-primary)', border: '1px solid var(--border)',
                              borderLeft: `3px solid ${color}`,
                            }}>
                              {rule.reg_t_initial && <div><span style={{ color: 'var(--text-muted)' }}>Reg T Initial:</span> <span style={{ color: 'var(--accent-amber)' }}>{rule.reg_t_initial}</span></div>}
                              {rule.finra_maintenance && <div><span style={{ color: 'var(--text-muted)' }}>FINRA Maint:</span> <span style={{ color: 'var(--accent-amber)' }}>{rule.finra_maintenance}</span></div>}
                              {rule.stress_range && <div><span style={{ color: 'var(--text-muted)' }}>Stress Range:</span> <span style={{ color: 'var(--accent-amber)' }}>{rule.stress_range}</span></div>}
                              {rule.leverage_factor != null && <div><span style={{ color: 'var(--text-muted)' }}>Leverage:</span> <span style={{ color: 'var(--accent-amber)' }}>{rule.leverage_factor}x</span></div>}
                              {rule.position_side && <div><span style={{ color: 'var(--text-muted)' }}>Side:</span> <span style={{ color: 'var(--text-secondary)' }}>{rule.position_side}</span></div>}
                              <div><span style={{ color: 'var(--text-muted)' }}>Formula:</span> <span style={{ color: 'var(--text-secondary)' }}>{rule.formula_type}</span></div>
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: 1 }}>Full Definition</div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{rule.definition}</div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {timelineSection && (
        <RegulatoryTimeline
          section={timelineSection}
          onClose={() => setTimelineSection(null)}
        />
      )}
    </div>
  )
}
