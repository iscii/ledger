export interface Action {
  id: string
  session_id: string
  seq: number
  ts: string
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown>
  reversible: boolean
  inverse_id: string | null
  status: 'ok' | 'error' | 'committed'
}

export interface Session {
  session_id: string
  action_count: number
  started_at: string
  last_action_at: string
}

export interface SessionDetail {
  session_id: string
  actions: Action[]
}

export interface RollbackResult {
  session_id: string
  rolled_back: string[]
  skipped: string[]
  errors: string[]
}

export interface ReplayResult {
  session_id: string
  replayed: number
  errors: string[]
}
