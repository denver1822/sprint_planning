export type Card = { value: string; type: 'numeric' | 'special' }
export type Participant = {
  id: string
  display_name: string
  is_online: boolean
  is_owner: boolean
  has_voted: boolean
}
export type Room = {
  code: string
  name: string
  state: 'LOBBY' | 'VOTING' | 'REVEALED' | 'FINISHED'
  version: number
  deck: { kind: string; cards: Card[] }
  participants: Participant[]
  tasks: Task[]
  active_task_id: string | null
  created_at: string
  updated_at: string
}
export type Task = { id: string; title: string; position: number; is_excluded: boolean }
export type Session = { room: Room; participant: Participant; participant_token: string | null; restored: boolean }
export type Round = { id: string; task_id: string | null; sequence: number; state: string; version: number }
export type Reveal = { round: Round; revealed_votes: Array<{ display_name: string; card_value: string; is_numeric: boolean }>; metrics: Record<string, unknown> }
export type RoomSnapshot = { room: Room; active_round: Round | null }
export type HistoryItem = { id: string; sequence: number; task_id: string | null; task_title: string | null; revealed_at: string; revealed_votes: Array<{ display_name: string; card_value: string; is_numeric: boolean }>; metrics: Record<string, unknown> }
export type JiraIssue = { key: string; title: string; url: string; snapshot: Record<string, string | null> }
export type JiraPreview = { issues: JiraIssue[]; start_at: number; max_results: number; total: number }
export type SessionSummary = { revealed_round_count: number; total_vote_count: number; numeric_vote_count: number; special_vote_count: number; exact_consensus_count: number; mean_agreement_index: number | null; distribution: Record<string, number>; special_cards: Record<string, number> }

type ApiError = { error?: { message?: string } }

async function request<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`/api${path}`, { ...init, headers })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiError
    throw new Error(body.error?.message ?? 'Не удалось выполнить запрос')
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  createRoom: (name: string, ownerName: string, kind: string) =>
    request<Session>('/rooms', { method: 'POST', body: JSON.stringify({ name, owner_name: ownerName, deck: { kind } }) }),
  getRoom: (code: string) => request<Room>(`/rooms/${encodeURIComponent(code)}`),
  getSnapshot: (code: string) => request<RoomSnapshot>(`/rooms/${encodeURIComponent(code)}/snapshot`),
  getHistory: (code: string) => request<HistoryItem[]>(`/rooms/${encodeURIComponent(code)}/history`),
  getSessionSummary: (code: string, token: string) => request<SessionSummary>(`/rooms/${encodeURIComponent(code)}/summary`, {}, token),
  joinRoom: (code: string, displayName: string | null, token?: string | null) =>
    request<Session>(`/rooms/${encodeURIComponent(code)}/join`, { method: 'POST', body: JSON.stringify(displayName ? { display_name: displayName } : {}) }, token),
  updateRoom: (code: string, version: number, body: Record<string, unknown>, token: string) =>
    request<Room>(`/rooms/${encodeURIComponent(code)}`, { method: 'PATCH', body: JSON.stringify({ ...body, expected_version: version }) }, token),
  createTask: (code: string, title: string, version: number, token: string) =>
    request<Task>(`/rooms/${code}/tasks`, { method: 'POST', body: JSON.stringify({ title, expected_version: version }) }, token),
  reorderTasks: (code: string, taskIds: string[], version: number, token: string) =>
    request<void>(`/rooms/${code}/tasks/order`, { method: 'PUT', body: JSON.stringify({ task_ids: taskIds, expected_version: version }) }, token),
  setActiveTask: (code: string, taskId: string | null, version: number, token: string) =>
    request<void>(`/rooms/${code}/active-task`, { method: 'PUT', body: JSON.stringify({ task_id: taskId, expected_version: version }) }, token),
  previewJira: (code: string, body: Record<string, unknown>, token: string) =>
    request<JiraPreview>(`/rooms/${code}/jira/preview`, { method: 'POST', body: JSON.stringify(body) }, token),
  importJira: (code: string, body: Record<string, unknown>, token: string) =>
    request(`/rooms/${code}/jira/import`, { method: 'POST', body: JSON.stringify(body) }, token),
  startRound: (code: string, version: number, token: string) =>
    request<Round>(`/rooms/${code}/rounds`, { method: 'POST', body: JSON.stringify({ expected_version: version, client_command_id: crypto.randomUUID() }) }, token),
  vote: (code: string, roundId: string, cardValue: string | null, token: string) =>
    request(`/rooms/${code}/rounds/${roundId}/vote`, { method: 'PUT', body: JSON.stringify({ card_value: cardValue }) }, token),
  cancelVote: (code: string, roundId: string, token: string) =>
    request<void>(`/rooms/${code}/rounds/${roundId}/vote`, { method: 'DELETE' }, token),
  reveal: (code: string, roundId: string, version: number, token: string) =>
    request<Reveal>(`/rooms/${code}/rounds/${roundId}/reveal`, { method: 'POST', body: JSON.stringify({ expected_version: version, client_command_id: crypto.randomUUID() }) }, token),
  newRound: (code: string, roundId: string, version: number, token: string) =>
    request<Round>(`/rooms/${code}/rounds/${roundId}/new`, { method: 'POST', body: JSON.stringify({ expected_version: version, client_command_id: crypto.randomUUID() }) }, token),
  finish: (code: string, version: number, token: string) =>
    request<Room>(`/rooms/${code}/finish`, { method: 'POST', body: JSON.stringify({ expected_version: version, client_command_id: crypto.randomUUID() }) }, token),
}

export type LocalSession = { token: string; participantId: string }
export const sessionStore = {
  get(code: string): LocalSession | null {
    const raw = localStorage.getItem(`planning-poker:${code}`)
    return raw ? (JSON.parse(raw) as LocalSession) : null
  },
  set(code: string, value: LocalSession) { localStorage.setItem(`planning-poker:${code}`, JSON.stringify(value)) },
}
