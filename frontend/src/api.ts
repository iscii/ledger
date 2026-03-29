import type { Session, SessionDetail, RollbackResult, ReplayResult, DiffResult } from './types'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  getSessions(): Promise<Session[]> {
    return request<Session[]>('/sessions')
  },

  getSession(id: string): Promise<SessionDetail> {
    return request<SessionDetail>(`/sessions/${encodeURIComponent(id)}`)
  },

  rollback(id: string): Promise<RollbackResult> {
    return request<RollbackResult>(`/sessions/${encodeURIComponent(id)}/rollback`, {
      method: 'POST',
    })
  },

  replay(id: string): Promise<ReplayResult> {
    return request<ReplayResult>(`/sessions/${encodeURIComponent(id)}/replay`, {
      method: 'POST',
    })
  },

  getDiff(sessionA: string, sessionB: string): Promise<DiffResult> {
    return request<DiffResult>(`/diff/${encodeURIComponent(sessionA)}/${encodeURIComponent(sessionB)}`)
  },
}
