import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { api, type HistoryItem, type JiraIssue, type Reveal, type Room, type Round, type SessionSummary, type Task, sessionStore } from './api'
import { type RoomSocketMessage, useRoomSocket } from './realtime/useRoomSocket'

const decks = [
  ['fibonacci', 'Фибоначчи'],
  ['modified_fibonacci', 'Modified Fibonacci'],
  ['powers_of_two', 'Степени двойки'],
] as const

export function App() {
  const match = window.location.pathname.match(/^\/room\/([^/]+)$/)
  return match ? <RoomScreen code={decodeURIComponent(match[1])} /> : <CreateRoom />
}

function CreateRoom() {
  const [name, setName] = useState('Оценка спринта')
  const [ownerName, setOwnerName] = useState('')
  const [deck, setDeck] = useState('fibonacci')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const session = await api.createRoom(name, ownerName, deck)
      if (!session.participant_token) throw new Error('Не удалось получить токен владельца')
      sessionStore.set(session.room.code, { token: session.participant_token, participantId: session.participant.id })
      window.location.assign(`/room/${session.room.code}`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Ошибка создания комнаты') } finally { setBusy(false) }
  }

  return <main className="landing"><section className="hero"><span className="eyebrow">Planning Poker</span><h1>Оценивайте задачи<br /><em>вместе, без влияния.</em></h1><p>Быстрая синхронная оценка в story points: откройте комнату, отправьте ссылку и раскройте карты одновременно.</p></section><form className="create-card" onSubmit={submit}><h2>Создать комнату</h2><label>Название комнаты<input value={name} onChange={e => setName(e.target.value)} maxLength={160} required /></label><label>Ваше имя<input value={ownerName} onChange={e => setOwnerName(e.target.value)} maxLength={80} required autoFocus /></label><fieldset><legend>Колода</legend><div className="deck-choices">{decks.map(([value, label]) => <label className="radio" key={value}><input type="radio" checked={deck === value} onChange={() => setDeck(value)} />{label}</label>)}</div></fieldset>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? 'Создаём…' : 'Создать и пригласить'}</button><p className="muted">Без регистрации. Владельцы по умолчанию не голосуют.</p></form></main>
}

function RoomScreen({ code }: { code: string }) {
  const [room, setRoom] = useState<Room | null>(null)
  const [round, setRound] = useState<Round | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [error, setError] = useState('')
  const [joinName, setJoinName] = useState('')
  const [loading, setLoading] = useState(true)
  const local = sessionStore.get(code)
  const token = local?.token ?? null
  const selfId = local?.participantId ?? null

  const onSocketMessage = useCallback((message: RoomSocketMessage) => {
    const payload = message.payload as { room?: Room; active_round?: Round } & Reveal
    if (message.type === 'room.snapshot' && payload.room) { setRoom(payload.room); setRound(payload.active_round ?? null); setLoading(false) }
    if (message.type === 'presence.changed') setRoom(current => current ? { ...current, participants: current.participants.map(p => p.id === (payload as unknown as { id: string }).id ? { ...p, ...(payload as unknown as object) } : p) } : current)
    if (message.type === 'round.started') {
      const startedRound = payload as unknown as Round
      setRound(startedRound)
      setRoom(current => current ? {
        ...current,
        state: 'VOTING',
        version: startedRound.version,
        participants: current.participants.map(participant => ({ ...participant, has_voted: false })),
      } : current)
    }
    if (message.type === 'round.revealed') { const reveal = payload as Reveal; void api.getHistory(code).then(setHistory); if (token) void api.getSessionSummary(code, token).then(setSummary); setRound(reveal.round); setRoom(current => current ? { ...current, state: 'REVEALED', version: reveal.round.version } : current) }
    if (message.type === 'room.finished' && payload) setRoom(payload as unknown as Room)
  }, [code, token])
  const { status } = useRoomSocket({ roomCode: code, participantToken: token, onMessage: onSocketMessage })

  useEffect(() => { api.getRoom(code).then(value => { setRoom(value); setLoading(false) }).catch(e => { setError(e.message); setLoading(false) }) }, [code])
  useEffect(() => { api.getHistory(code).then(setHistory).catch(() => undefined) }, [code])
  useEffect(() => { if (token) void api.getSessionSummary(code, token).then(setSummary).catch(() => undefined) }, [code, token])
  useEffect(() => {
    if (!token) return
    const synchronize = () => {
      api.getSnapshot(code).then(snapshot => {
        setRoom(snapshot.room)
        setRound(snapshot.active_round)
      }).catch(() => undefined)
    }
    synchronize()
    const timer = window.setInterval(synchronize, 2000)
    return () => window.clearInterval(timer)
  }, [code, token])
  const self = useMemo(() => room?.participants.find(p => p.id === selfId), [room, selfId])

  async function join(event: FormEvent) { event.preventDefault(); try { const session = await api.joinRoom(code, joinName || null, token); const activeToken = session.participant_token ?? token; if (!activeToken) throw new Error('Токен участника не получен'); sessionStore.set(code, { token: activeToken, participantId: session.participant.id }); setRoom(session.room); window.location.reload() } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось войти') } }
  async function action(run: () => Promise<unknown>) {
    try {
      setError('')
      await run()
      const snapshot = await api.getSnapshot(code)
      setRoom(snapshot.room)
      setRound(snapshot.active_round)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Команда не выполнена')
    }
  }
  if (loading) return <main className="center">Загружаем комнату…</main>
  if (!room) return <main className="center"><p role="alert">{error || 'Комната не найдена'}</p><a href="/">На главную</a></main>
  if (!token || !self) return <main className="join-page"><section><span className="eyebrow">Приглашение в комнату</span><h1>{room.name}</h1><p>Введите имя, чтобы присоединиться к оценке.</p><form onSubmit={join}><label>Ваше имя<input value={joinName} onChange={e => setJoinName(e.target.value)} required autoFocus /></label>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary">Войти в комнату</button></form></section></main>

  const isOwner = self.is_owner
  return <main className="room-shell"><header className="room-header"><a className="brand" href="/">PP</a><div><span className="eyebrow">Комната</span><h1>{room.name}</h1></div><div className="connection" aria-label="Статус соединения"><i className={status} />{status === 'connected' ? 'В сети' : 'Переподключение'}</div><button className="secondary" onClick={() => navigator.clipboard.writeText(window.location.href)}>Скопировать ссылку</button></header>{error && <p className="toast" role="alert">{error}</p>}<div className="room-grid"><aside className="sidebar"><section className="panel"><h2>Участники <span>{room.participants.length}</span></h2><ul className="participants">{room.participants.map(p => <li key={p.id}><i className={p.is_online ? 'online' : 'offline'} /><span>{p.display_name}{p.is_owner && ' · владелец'}</span>{room.state === 'VOTING' && p.has_voted && <b aria-label="Проголосовал">✓</b>}</li>)}</ul></section><TaskList room={room} token={token} canManage={isOwner} onAction={action} />{isOwner && <JiraPanel room={room} token={token} onAction={action} />}{isOwner && <RoomSettings room={room} token={token} onError={setError} onUpdated={setRoom} />}</aside><section className="game"><RoundPanel room={room} round={round} self={self} token={token} onAction={action} onError={setError} onReveal={() => { void api.getHistory(code).then(setHistory); void api.getSessionSummary(code, token).then(setSummary) }} /><section className="panel history"><h2>История раундов</h2>{history.length ? history.map(item => <div className="history-row" key={item.id}><span>Раунд {item.sequence}{item.task_title ? ` · ${item.task_title}` : ''}</span><strong>{item.revealed_votes.map(v => v.card_value).join(' · ')}</strong><small>{String(item.metrics.vote_count ?? 0)} голосов · среднее {item.metrics.mean === null ? '—' : String(item.metrics.mean)} · согласие {item.metrics.agreement_index === null ? '—' : `${Math.round(Number(item.metrics.agreement_index) * 100)}%`}</small></div>) : <p className="muted">Раскрытые раунды появятся здесь.</p>}<SessionSummaryPanel summary={summary} /></section></section></div>{isOwner && room.state !== 'FINISHED' && <button className="finish" onClick={() => action(() => api.finish(code, room.version, token))}>Завершить сессию</button>}</main>
}

function SessionSummaryPanel({ summary }: { summary: SessionSummary | null }) {
  if (!summary || !summary.revealed_round_count) return null
  return <div className="session-summary"><h3>Сводка сессии</h3><p>{summary.revealed_round_count} раундов · {summary.total_vote_count} голосов · точное согласие: {summary.exact_consensus_count}</p><p>Средний индекс согласия: {summary.mean_agreement_index === null ? '—' : `${Math.round(summary.mean_agreement_index * 100)}%`}</p><p>Распределение: {Object.entries(summary.distribution).map(([value, count]) => `${value}: ${count}`).join(' · ') || 'нет числовых голосов'}</p>{Object.keys(summary.special_cards).length > 0 && <p>Служебные карты: {Object.entries(summary.special_cards).map(([value, count]) => `${value}: ${count}`).join(' · ')}</p>}</div>
}

function JiraPanel({ room, token, onAction }: { room: Room; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [baseUrl, setBaseUrl] = useState('')
  const [email, setEmail] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [jql, setJql] = useState('project = YOUR_PROJECT ORDER BY created DESC')
  const [issues, setIssues] = useState<JiraIssue[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const request = { connection: { base_url: baseUrl, email: email || null, api_token: apiToken }, jql, start_at: 0, max_results: 25 }
  return <section className="panel jira"><h2>Jira</h2><label>Адрес Jira<input type="url" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://company.atlassian.net" /></label><label>Email<input type="email" value={email} onChange={event => setEmail(event.target.value)} /></label><label>API token<input type="password" value={apiToken} onChange={event => setApiToken(event.target.value)} autoComplete="off" /></label><label>JQL<textarea value={jql} onChange={event => setJql(event.target.value)} rows={3} /></label><button className="secondary" disabled={!baseUrl || !apiToken || !jql} onClick={() => api.previewJira(room.code, request, token).then(result => { setIssues(result.issues); setSelected(result.issues.map(issue => issue.key)) })}>Показать задачи</button>{issues.length > 0 && <><ul className="jira-issues">{issues.map(issue => <li key={issue.key}><label><input type="checkbox" checked={selected.includes(issue.key)} onChange={() => setSelected(current => current.includes(issue.key) ? current.filter(key => key !== issue.key) : [...current, issue.key])} />{issue.key} · {issue.title}</label></li>)}</ul><button className="primary" disabled={!selected.length} onClick={() => void onAction(async () => { await api.importJira(room.code, { ...request, expected_version: room.version, selected_keys: selected }, token); setIssues([]); setSelected([]); setApiToken('') })}>Импортировать выбранные</button></>}<p className="muted">Токен используется только для запроса и не сохраняется.</p></section>
}

function TaskList({ room, token, canManage, onAction }: { room: Room; token: string; canManage: boolean; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [title, setTitle] = useState('')
  const tasks = [...room.tasks].sort((left, right) => left.position - right.position)
  const activeTask = tasks.find(task => task.id === room.active_task_id)
  const move = (task: Task, direction: -1 | 1) => {
    const index = tasks.findIndex(item => item.id === task.id)
    const target = index + direction
    if (target < 0 || target >= tasks.length) return
    const ordered = [...tasks]
    ;[ordered[index], ordered[target]] = [ordered[target], ordered[index]]
    void onAction(() => api.reorderTasks(room.code, ordered.map(item => item.id), room.version, token))
  }
  return <section className="panel tasks"><h2>Задачи</h2>{activeTask && <p className="active-task">Активная: <strong>{activeTask.title}</strong></p>}<ol>{tasks.map((task, index) => <li key={task.id} className={task.id === room.active_task_id ? 'active' : ''}><button className="task-title" disabled={!canManage} onClick={() => void onAction(() => api.setActiveTask(room.code, task.id, room.version, token))}>{task.title}</button>{canManage && <span><button aria-label="Выше" disabled={index === 0} onClick={() => move(task, -1)}>↑</button><button aria-label="Ниже" disabled={index === tasks.length - 1} onClick={() => move(task, 1)}>↓</button></span>}</li>)}</ol>{canManage && <form className="task-form" onSubmit={event => { event.preventDefault(); if (!title.trim()) return; void onAction(async () => { await api.createTask(room.code, title, room.version, token); setTitle('') }) }}><input value={title} onChange={event => setTitle(event.target.value)} placeholder="Новая задача" maxLength={500} /><button className="secondary">Добавить</button></form>}{!tasks.length && <p className="muted">Добавьте задачу для оценки.</p>}</section>
}

function RoomSettings({ room, token, onError, onUpdated }: { room: Room; token: string; onError: (v: string) => void; onUpdated: (v: Room) => void }) { const [name, setName] = useState(room.name); return <section className="panel settings"><h2>Настройки</h2><label>Название<input value={name} onChange={e => setName(e.target.value)} /></label><button className="secondary" onClick={() => api.updateRoom(room.code, room.version, { name }, token).then(onUpdated).catch(e => onError(e.message))}>Сохранить</button></section> }

function VotingTable({ room }: { room: Room }) {
  const voters = room.participants.filter(participant => !participant.is_owner)
  const voted = voters.filter(participant => participant.has_voted).length
  return <section className="poker-table" aria-label="Игральный стол"><header><span>Игральный стол</span><strong>{voted} из {voters.length} проголосовали</strong></header><div className="table-felt"><div className="table-cards">{voters.map(participant => <div className="table-seat" key={participant.id}><div className={`table-card${participant.has_voted ? ' dealt' : ''}`} aria-label={participant.has_voted ? `${participant.display_name} проголосовал` : `${participant.display_name} ещё выбирает`}>{participant.has_voted && <span>PP</span>}</div><small>{participant.display_name}</small></div>)}</div></div></section>
}

function RoundPanel({ room, round, self, token, onAction, onError, onReveal }: { room: Room; round: Round | null; self: { is_owner: boolean; has_voted: boolean }; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void>; onError: (v: string) => void; onReveal: (v: Reveal) => void }) {
  const [selectedCard, setSelectedCard] = useState<{ roundId: string; value: string } | null>(null)
  const selectedValue =
    selectedCard !== null && selectedCard.roundId === round?.id ? selectedCard.value : null
  const code = room.code
  if (room.state === 'FINISHED') return <section className="panel finished"><h2>Сессия завершена</h2><p>Комната доступна только для просмотра.</p></section>
  if (room.state === 'LOBBY') return <section className="panel lobby"><span className="eyebrow">Лобби</span><h2>Готовы начать оценку?</h2><p>Любой подключённый участник может запустить раунд.</p><button className="primary" onClick={() => onAction(() => api.startRound(code, room.version, token))}>Начать голосование</button></section>
  if (room.state === 'REVEALED' && round) return <section className="panel revealed"><span className="eyebrow">Раунд {round.sequence}</span><h2>Карты раскрыты</h2><p>Обсудите оценки и начните следующий раунд.</p><button className="primary" onClick={() => onAction(() => api.newRound(code, round.id, room.version, token))}>Новый раунд</button></section>
  return <section className="panel voting"><div className="round-top"><div><span className="eyebrow">Раунд {round?.sequence ?? ''}</span><h2>Выберите карту</h2></div><button className="secondary" onClick={() => round && onAction(async () => { const reveal = await api.reveal(code, round.id, room.version, token); onReveal(reveal) })}>Раскрыть карты</button></div><VotingTable room={room} />{self.is_owner ? <p className="muted">Вы управляете раундом, но не голосуете.</p> : self.has_voted ? <div className="confirmed-vote"><p className="vote-confirmation">Ваш выбор подтверждён. Карта лежит на столе рубашкой вверх.</p><button className="secondary" disabled={!round} onClick={() => round && onAction(() => api.cancelVote(code, round.id, token))}>Отменить голос</button></div> : <><div className="cards" role="group" aria-label="Колода">{room.deck.cards.map(card => <button className={`card${selectedValue === card.value ? ' selected' : ''}`} aria-pressed={selectedValue === card.value} key={card.value} onClick={() => round && setSelectedCard({ roundId: round.id, value: card.value })}><span>{card.value}</span></button>)}</div><div className="vote-actions"><button className="secondary" disabled={!selectedValue} onClick={() => setSelectedCard(null)}>Отменить выбор</button><button className="primary" disabled={!selectedValue || !round} onClick={() => round ? onAction(() => api.vote(code, round.id, selectedValue, token)) : onError('Раунд не найден')}>Подтвердить выбор</button></div><p className="vote-confirmation" aria-live="polite">{selectedValue ? `Выбрано: ${selectedValue}. Подтвердите выбор.` : 'Выберите карту — её значение останется скрытым.'}</p></>}<p className="muted">Значения карт раскроются одновременно.</p></section>
}
