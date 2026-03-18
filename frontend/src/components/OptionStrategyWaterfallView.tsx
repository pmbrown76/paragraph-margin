import { useState, useEffect, useMemo, Fragment } from 'react'
import { RegulatoryTimeline } from './RegulatoryTimeline'

interface Strategy {
  name: string
  rule_id: string
  section: string
  finra_category: string
  legs: string[]
  constraints: string
  definition: string
  margin: string
  formula_detail: string
}

interface WaterfallCategory {
  priority: number
  name: string
  rationale: string
  citation: string
  strategies: Strategy[]
}

interface WaterfallData {
  categories: WaterfallCategory[]
}

const priorityColors: Record<number, string> = {
  0: '#10b981', 1: '#6366f1', 2: '#8b5cf6', 3: '#a78bfa', 4: '#14b8a6',
  5: '#f59e0b', 6: '#f97316', 7: '#ef4444', 8: '#3b82f6',
  9: '#ec4899', 10: '#06b6d4', 11: '#64748b', 12: '#dc2626',
}

type SortColumn = 'priority' | 'category' | 'section' | 'strategy' | 'legs' | 'definition'
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

export function OptionStrategyWaterfallView() {
  const [data, setData] = useState<WaterfallData | null>(null)
  const [expandedStrategy, setExpandedStrategy] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [timelineSection, setTimelineSection] = useState<string | null>(null)
  const [sortCol, setSortCol] = useState<SortColumn>('priority')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  useEffect(() => {
    fetch('/api/option-strategy-waterfall')
      .then(r => r.json())
      .then(d => setData(d))
  }, [])

  const handleSort = (col: SortColumn) => {
    if (col === sortCol) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  const categories = data?.categories || []
  const totalStrategies = categories.reduce((sum, c) => sum + (c.strategies?.length || 0), 0)
  const mono = "'SF Mono','Fira Code','Consolas',monospace"

  const allRows = useMemo(() =>
    categories.flatMap(cat =>
      (cat.strategies || []).map(strat => ({ cat, strat }))
    ), [categories])

  const filteredRows = useMemo(() =>
    allRows.filter(({ cat, strat }) => {
      const matchesCategory = !categoryFilter || String(cat.priority) === categoryFilter
      const matchesSearch = !search || (() => {
        const s = search.toLowerCase()
        return (
          strat.name.toLowerCase().includes(s) ||
          strat.definition.toLowerCase().includes(s) ||
          cat.name.toLowerCase().includes(s) ||
          cat.rationale.toLowerCase().includes(s) ||
          (cat.citation || '').toLowerCase().includes(s) ||
          (strat.section || '').toLowerCase().includes(s) ||
          (strat.finra_category || '').toLowerCase().includes(s) ||
          (strat.margin || '').toLowerCase().includes(s) ||
          (strat.constraints || '').toLowerCase().includes(s) ||
          (strat.formula_detail || '').toLowerCase().includes(s) ||
          strat.legs.some(l => l.toLowerCase().includes(s)) ||
          (strat.rule_id || '').toLowerCase().includes(s)
        )
      })()
      return matchesCategory && matchesSearch
    }), [allRows, search, categoryFilter])

  const sortedRows = useMemo(() => {
    const rows = [...filteredRows]
    const cmp = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: 'base' })
    const dir = sortDir === 'asc' ? 1 : -1
    rows.sort((a, b) => {
      switch (sortCol) {
        case 'priority': return dir * (a.cat.priority - b.cat.priority)
        case 'category': return dir * cmp(a.cat.name, b.cat.name)
        case 'section': return dir * cmp(a.strat.section || '', b.strat.section || '')
        case 'strategy': return dir * cmp(a.strat.name, b.strat.name)
        case 'legs': return dir * cmp(a.strat.legs.join(' '), b.strat.legs.join(' '))
        case 'definition': return dir * cmp(a.strat.definition, b.strat.definition)
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
        <h2>Option Strategy Waterfall</h2>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          {categories.length} categories, {totalStrategies} strategies
        </span>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, padding: '0 16px 16px', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search strategies, legs, definitions..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 320 }}
        />
        <select
          value={categoryFilter}
          onChange={e => setCategoryFilter(e.target.value)}
        >
          <option value="">All Categories</option>
          {categories.map(c => <option key={c.priority} value={String(c.priority)}>{c.priority}. {c.name}</option>)}
        </select>
        {(search || categoryFilter) && (
          <button className="btn-secondary btn-sm" onClick={() => { setSearch(''); setCategoryFilter('') }}>Clear</button>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          {filteredRows.length} of {totalStrategies} strategies
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
              <SortHeader label="Strategy" column="strategy" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 200 }} />
              <SortHeader label="Legs" column="legs" current={sortCol} dir={sortDir} onSort={handleSort} style={{ width: 300 }} />
              <SortHeader label="Definition" column="definition" current={sortCol} dir={sortDir} onSort={handleSort} />
            </tr>
          </thead>
          <tbody>
            {sortedRows.map(({ cat, strat }, idx) => {
              const color = priorityColors[cat.priority] || 'var(--text-secondary)'
              const stratKey = `${cat.priority}-${strat.name}`
              const isExpanded = expandedStrategy === stratKey
              const isNewCategory = showCategorySeparators && cat.priority !== lastCatPriority
              if (showCategorySeparators) lastCatPriority = cat.priority
              const catRowCount = sortedRows.filter(r => r.cat.priority === cat.priority).length

              return (
                <Fragment key={stratKey}>
                  {/* Category separator row */}
                  {isNewCategory && (
                    <tr style={{ background: 'rgba(79, 143, 247, 0.06)', borderTop: `2px solid ${color}` }}>
                      <td style={{ fontWeight: 700, fontSize: 13, color, textAlign: 'center' }}>{cat.priority}</td>
                      <td colSpan={2} style={{ fontWeight: 700, fontSize: 13 }}>
                        <span style={{ borderLeft: `3px solid ${color}`, paddingLeft: 8 }}>{cat.name}</span>
                        <span style={{ marginLeft: 12, fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>
                          {catRowCount} {catRowCount === 1 ? 'strategy' : 'strategies'}
                        </span>
                      </td>
                      <td style={{ fontSize: 11, fontFamily: mono, color: 'var(--text-muted)' }}>{cat.citation}</td>
                      <td></td>
                      <td style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{cat.rationale}</td>
                    </tr>
                  )}

                  {/* Strategy row */}
                  <tr
                    className="clickable"
                    onClick={() => setExpandedStrategy(isExpanded ? null : stratKey)}
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
                        <span>{strat.section || ''}</span>
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
                          onClick={e => { e.stopPropagation(); setTimelineSection(strat.section || null) }}
                          title="View regulatory timeline"
                        >
                          Reg Lineage
                        </span>
                      </div>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>{strat.name}</span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        {strat.legs.map((leg, i) => (
                          <div key={i} style={{ fontSize: 11, fontFamily: mono, color: 'var(--text-secondary)' }}>
                            {leg}
                          </div>
                        ))}
                      </div>
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                      {strat.definition.length > 180 && !isExpanded
                        ? strat.definition.slice(0, 180) + '...'
                        : strat.definition}
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
                          {strat.rule_id ? (
                            <span style={{
                              fontSize: 11, fontFamily: mono, fontWeight: 600,
                              padding: '2px 8px', borderRadius: 4,
                              background: 'rgba(99, 102, 241, 0.15)',
                              color: '#a5b4fc',
                            }}>
                              {strat.rule_id}
                            </span>
                          ) : (
                            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>No published rule (long options — no margin requirement)</span>
                          )}
                          <span style={{
                            fontSize: 11, fontFamily: mono,
                            padding: '2px 8px', borderRadius: 4,
                            background: 'rgba(59, 130, 246, 0.12)',
                            color: 'var(--accent-blue)',
                          }}>
                            FINRA {strat.section}
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
                            onClick={() => setTimelineSection(strat.section || null)}
                            title="View regulatory timeline"
                          >
                            Reg Lineage
                          </span>
                          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                            {strat.rule_id ? 'ParagraphReg Published Rule' : ''}
                          </span>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                          <div>
                            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: 1 }}>Constraints</div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{strat.constraints}</div>
                          </div>
                          <div>
                            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: 1 }}>Margin Treatment</div>
                            <div style={{
                              fontSize: 12, fontFamily: mono, lineHeight: 1.6,
                              padding: '6px 10px', borderRadius: 4,
                              background: 'var(--bg-primary)', border: '1px solid var(--border)',
                              borderLeft: `3px solid ${color}`,
                              color: 'var(--accent-amber)',
                            }}>
                              {strat.margin}
                            </div>
                          </div>
                        </div>
                        {strat.formula_detail && (
                          <div style={{ marginTop: 16 }}>
                            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6, letterSpacing: 1 }}>Formula / Calculation Steps</div>
                            <pre style={{
                              fontSize: 12, fontFamily: mono, lineHeight: 1.7,
                              padding: '10px 14px', borderRadius: 4,
                              background: 'var(--bg-primary)', border: '1px solid var(--border)',
                              borderLeft: `3px solid ${color}`,
                              color: 'var(--text-primary)',
                              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              margin: 0, overflowX: 'auto',
                            }}>
                              {strat.formula_detail}
                            </pre>
                          </div>
                        )}
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
