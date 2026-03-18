import { useState, useEffect, useCallback } from 'react'
import { RulesBrowser } from './components/RulesBrowser'
import { FormulaTester } from './components/FormulaTester'
import { Overview } from './components/Overview'
import { OptionStrategyWaterfallView } from './components/OptionStrategyWaterfallView'
import { AssetClassWaterfallView } from './components/AssetClassWaterfallView'
import type { Rule, Stats } from './types'

type Tab = 'rules' | 'tester' | 'strategies' | 'overview'
type StrategySubTab = 'option-strategies' | 'equity' | 'fixed-income' | 'etf' | 'concentrated' | 'day-trading' | 'portfolio-margin' | 'reg-t-equity' | 'reg-t-fixed-income' | 'reg-t-options' | 'reg-t-special-accounts' | 'sec-15c3-1' | 'sec-15c3-3'

const strategySubTabLabels: Record<StrategySubTab, string> = {
  'option-strategies': 'Option Strategies',
  'equity': 'Equities',
  'fixed-income': 'Fixed Income',
  'etf': 'ETF / ETP',
  'concentrated': 'Concentrated',
  'day-trading': 'Day Trading',
  'portfolio-margin': 'Portfolio Margin',
  'reg-t-equity': 'Reg T: Equity',
  'reg-t-fixed-income': 'Reg T: Fixed Income',
  'reg-t-options': 'Reg T: Options',
  'reg-t-special-accounts': 'Reg T: SMA & Accounts',
  'sec-15c3-1': 'SEC 15c3-1: Net Capital',
  'sec-15c3-3': 'SEC 15c3-3: Customer Protection',
}

export function App() {
  const [tab, setTab] = useState<Tab>('rules')
  const [strategySubTab, setStrategySubTab] = useState<StrategySubTab>('option-strategies')
  const [rules, setRules] = useState<Rule[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchRules = useCallback(() => {
    fetch('/api/rules')
      .then(r => r.json())
      .then(d => { setRules(d.rules ?? []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const fetchStats = useCallback(() => {
    fetch('/api/stats')
      .then(r => r.json())
      .then(d => setStats(d))
      .catch(() => {})
  }, [])

  useEffect(() => { fetchRules(); fetchStats() }, [fetchRules, fetchStats])

  const handleReload = useCallback(() => {
    setLoading(true)
    fetch('/api/reload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(r => r.json())
      .then(() => { fetchRules(); fetchStats() })
      .catch(() => setLoading(false))
  }, [fetchRules, fetchStats])

  return (
    <div className="app">
      <header className="header">
        <h1>ParagraphMargin</h1>
        <span className="subtitle">
          {stats ? `${stats.total} rules loaded` : 'Loading...'}
          {stats?.rules_dir ? ` from ${stats.rules_dir.split('/').slice(-2).join('/')}` : ''}
        </span>
      </header>

      <nav className="tabs">
        <button className={`tab${tab === 'rules' ? ' active' : ''}`} onClick={() => setTab('rules')}>Rules</button>
        <button className={`tab${tab === 'tester' ? ' active' : ''}`} onClick={() => setTab('tester')}>Tester</button>
        <button className={`tab${tab === 'strategies' ? ' active' : ''}`} onClick={() => setTab('strategies')}>Strategies</button>
        <button className={`tab${tab === 'overview' ? ' active' : ''}`} onClick={() => setTab('overview')}>Overview</button>
      </nav>

      <main className="main">
        {tab === 'rules' && <RulesBrowser rules={rules} loading={loading} onRuleUpdated={fetchRules} />}
        {tab === 'tester' && <FormulaTester rules={rules} />}
        {tab === 'strategies' && (
          <>
            <div className="subtabs">
              {(Object.keys(strategySubTabLabels) as StrategySubTab[]).map(st => (
                <button
                  key={st}
                  className={`subtab${strategySubTab === st ? ' active' : ''}`}
                  onClick={() => setStrategySubTab(st)}
                >
                  {strategySubTabLabels[st]}
                </button>
              ))}
            </div>
            {strategySubTab === 'option-strategies' && <OptionStrategyWaterfallView />}
            {strategySubTab !== 'option-strategies' && <AssetClassWaterfallView key={strategySubTab} assetClass={strategySubTab} />}
          </>
        )}
        {tab === 'overview' && <Overview stats={stats} onReload={handleReload} />}
      </main>
    </div>
  )
}
