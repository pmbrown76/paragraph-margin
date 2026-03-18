import { useState, useEffect } from 'react'

interface Amendment {
  date: string
  source: string
  change: string
}

interface SectionTimeline {
  section: string
  title: string
  original: { date: string; source: string; text: string }
  amendments: Amendment[]
  current_interpretation: string
  cross_cutting_amendments: { id: string; date: string; title: string; source: string; impact: string }[]
  reference_sources: { id: string; title: string; version?: string; date?: string; role: string }[]
}

const mono = "'SF Mono','Fira Code','Consolas',monospace"

export function RegulatoryTimeline({ section, onClose }: { section: string; onClose: () => void }) {
  const [data, setData] = useState<SectionTimeline | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/regulatory-timeline/${encodeURIComponent(section)}`)
      .then(r => {
        if (!r.ok) throw new Error('Not found')
        return r.json()
      })
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [section])

  // Build combined timeline from original + amendments
  const timelineEntries: { date: string; label: string; source: string; text: string; type: 'original' | 'amendment' | 'cross_cutting' }[] = []

  if (data) {
    timelineEntries.push({
      date: data.original.date,
      label: 'Original Rule',
      source: data.original.source,
      text: data.original.text,
      type: 'original',
    })

    for (const a of data.amendments) {
      timelineEntries.push({
        date: a.date,
        label: 'Amendment',
        source: a.source,
        text: a.change,
        type: 'amendment',
      })
    }

    // Add cross-cutting amendments that aren't already represented
    const amendmentSources = new Set(data.amendments.map(a => a.source))
    for (const cc of data.cross_cutting_amendments) {
      if (!amendmentSources.has(cc.source) && !amendmentSources.has(cc.id.replace('_', ' '))) {
        timelineEntries.push({
          date: cc.date,
          label: cc.title,
          source: cc.source,
          text: cc.impact,
          type: 'cross_cutting',
        })
      }
    }

    timelineEntries.sort((a, b) => a.date.localeCompare(b.date))
  }

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={e => e.stopPropagation()} style={{ maxWidth: 620 }}>
        <div className="drawer-header">
          <div>
            <span style={{ fontFamily: mono, fontSize: 14, color: 'var(--accent-blue)' }}>
              {section.startsWith('220.') ? `Reg T ${section}` : section.startsWith('15c3-') || section.startsWith('17a-') || section.startsWith('Exhibit A') ? `SEC ${section}` : `FINRA ${section}`}
            </span>
            {data && (
              <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4 }}>{data.title}</div>
            )}
          </div>
          <button className="btn-secondary btn-sm" onClick={onClose}>Close</button>
        </div>

        <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
          {loading && <div style={{ color: 'var(--text-muted)' }}>Loading...</div>}

          {!loading && !data && (
            <div style={{ color: 'var(--text-muted)' }}>
              No timeline data available for this section.
            </div>
          )}

          {data && (
            <>
              {/* Timeline */}
              <div style={{ position: 'relative', paddingLeft: 20 }}>
                {/* Vertical line */}
                <div style={{
                  position: 'absolute', left: 6, top: 8, bottom: 8,
                  width: 2, background: 'var(--border)',
                }} />

                {timelineEntries.map((entry, i) => (
                  <div key={i} style={{ position: 'relative', marginBottom: 20 }}>
                    {/* Dot */}
                    <div style={{
                      position: 'absolute', left: -17, top: 6,
                      width: 10, height: 10, borderRadius: '50%',
                      background: entry.type === 'original' ? '#6366f1'
                        : entry.type === 'amendment' ? '#f59e0b'
                        : '#64748b',
                      border: '2px solid var(--bg-secondary)',
                    }} />

                    {/* Date + source */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{
                        fontSize: 11, fontFamily: mono, fontWeight: 700,
                        color: entry.type === 'original' ? '#a5b4fc'
                          : entry.type === 'amendment' ? '#fbbf24'
                          : 'var(--text-muted)',
                      }}>
                        {entry.date}
                      </span>
                      <span style={{
                        fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                        padding: '1px 6px', borderRadius: 3, letterSpacing: 0.5,
                        background: entry.type === 'original' ? 'rgba(99, 102, 241, 0.15)'
                          : entry.type === 'amendment' ? 'rgba(245, 158, 11, 0.15)'
                          : 'rgba(100, 116, 139, 0.15)',
                        color: entry.type === 'original' ? '#a5b4fc'
                          : entry.type === 'amendment' ? '#fbbf24'
                          : 'var(--text-muted)',
                      }}>
                        {entry.label}
                      </span>
                    </div>

                    {/* Source */}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                      {entry.source}
                    </div>

                    {/* Text */}
                    <div style={{
                      fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6,
                      padding: '8px 12px', borderRadius: 4,
                      background: 'var(--bg-primary)', border: '1px solid var(--border)',
                      borderLeft: `3px solid ${
                        entry.type === 'original' ? '#6366f1'
                          : entry.type === 'amendment' ? '#f59e0b'
                          : '#64748b'
                      }`,
                    }}>
                      {entry.text}
                    </div>
                  </div>
                ))}
              </div>

              {/* Current interpretation */}
              <div style={{
                marginTop: 24, padding: '12px 16px', borderRadius: 6,
                background: 'rgba(20, 184, 166, 0.08)',
                border: '1px solid rgba(20, 184, 166, 0.25)',
              }}>
                <div style={{
                  fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                  color: '#14b8a6', letterSpacing: 1, marginBottom: 6,
                }}>
                  Current Interpretation
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-primary)', lineHeight: 1.7 }}>
                  {data.current_interpretation}
                </div>
              </div>

              {/* Reference sources */}
              {data.reference_sources.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{
                    fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                    color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 8,
                  }}>
                    Reference Sources
                  </div>
                  {data.reference_sources.map(ref => (
                    <div key={ref.id} style={{
                      fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5,
                      marginBottom: 6, paddingLeft: 10,
                      borderLeft: '2px solid var(--border)',
                    }}>
                      <span style={{ fontWeight: 600 }}>{ref.title}</span>
                      {ref.version && <span style={{ color: 'var(--text-muted)' }}> ({ref.version})</span>}
                      {ref.date && <span style={{ color: 'var(--text-muted)' }}> — {ref.date}</span>}
                      <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>{ref.role}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
