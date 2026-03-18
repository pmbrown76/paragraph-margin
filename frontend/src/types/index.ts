export interface Formula {
  type: string
  rate: number
  amount: number
  premium_pct: number
  underlying_pct: number
  otm_deduction: boolean
  minimum_underlying_pct: number
  minimum_per_contract: number
  multiplier: number
  floor_rate: number
  per_contract_minimum: number
  calculation: string
  description: string
}

export interface Minimum {
  type: string
  amount: number
}

export interface Rule {
  id: string
  description: string
  citation: string
  conditions: Record<string, unknown>
  asset_class: string
  formula: Formula | null
  minimum: Minimum | null
  produces_calculation: boolean
  calculation_status: string
  notes: string
  source_quote: string
  type: string
  rule_category: string
  rule_group: string
  regulation: string
}

export interface RulesResponse {
  rules: Rule[]
  total: number
}

export interface TestResult {
  margin: string | null
  margin_float: number | null
  rule_id: string
  formula_type: string | null
  context_used: Record<string, string>
  error?: string
}

export interface Stats {
  total: number
  rules_dir: string | null
  by_regulation: Record<string, number>
  by_formula_type: Record<string, number>
  disabled_count: number
}
