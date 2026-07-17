import { FormEvent, useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'

import { api, type Card, type DeckInput, type HistoryItem, type JiraIssue, type Reveal, type Room, type Round, type SessionSummary, type Task, sessionStore } from './api'
import { type RoomSocketMessage, useRoomSocket } from './realtime/useRoomSocket'

const decks = [
  ['fibonacci', 'Фибоначчи'],
  ['modified_fibonacci', 'Modified Fibonacci'],
  ['powers_of_two', 'Степени двойки'],
  ['custom', 'Своя колода'],
] as const

export function App() {
  const match = window.location.pathname.match(/^\/room\/([^/]+)$/)
  return match ? <RoomScreen code={decodeURIComponent(match[1])} /> : <CreateRoom />
}

function CreateRoom() {
  const [name, setName] = useState('Оценка спринта')
  const [ownerName, setOwnerName] = useState('')
  const [deck, setDeck] = useState('fibonacci')
  const [customCards, setCustomCards] = useState('1, 2, 3, 5, 8, 13, 21')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const cards: Card[] | undefined = deck === 'custom' ? customCards.split(',').map(value => value.trim()).filter(Boolean).map(value => ({ value, type: Number.isFinite(Number(value)) ? 'numeric' : 'special' })) : undefined
      if (deck === 'custom' && !cards?.some(card => card.type === 'numeric')) throw new Error('В своей колоде должна быть хотя бы одна числовая карта')
      const deckInput: DeckInput = cards ? { kind: deck, cards } : { kind: deck }
      const session = await api.createRoom(name, ownerName, deckInput)
      if (!session.participant_token) throw new Error('Не удалось получить токен владельца')
      sessionStore.set(session.room.code, { token: session.participant_token, participantId: session.participant.id })
      window.location.assign(`/room/${session.room.code}`)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Ошибка создания комнаты') } finally { setBusy(false) }
  }

  return <main className="landing"><section className="hero"><span className="eyebrow">Planning Poker</span><h1>Планирование<br /><em>спринта</em></h1><p>Быстрая синхронная оценка в story points: откройте комнату, отправьте ссылку и раскройте карты одновременно.</p></section><form className="create-card" onSubmit={submit}><h2>Создать комнату</h2><label>Название комнаты<input value={name} onChange={e => setName(e.target.value)} maxLength={160} required /></label><label>Ваше имя<input value={ownerName} onChange={e => setOwnerName(e.target.value)} maxLength={80} required autoFocus /></label><fieldset><legend>Колода</legend><div className="deck-choices">{decks.map(([value, label]) => <label className="radio" key={value}><input type="radio" checked={deck === value} onChange={() => setDeck(value)} />{label}</label>)}</div>{deck === 'custom' && <label className="custom-deck">Карты через запятую<input value={customCards} onChange={event => setCustomCards(event.target.value)} placeholder="1, 2, 3, 5, 8, 13, 21" /><small>Числа участвуют в аналитике; остальные значения считаются служебными.</small></label>}</fieldset>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? 'Создаём…' : 'Создать и пригласить'}</button><p className="muted">Без регистрации. Администратор может голосовать или остаться наблюдателем.</p></form></main>
}

function RoomScreen({ code }: { code: string }) {
  const [room, setRoom] = useState<Room | null>(null)
  const [round, setRound] = useState<Round | null>(null)
  const [revealedVotes, setRevealedVotes] = useState<Reveal['revealed_votes']>([])
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [copied, setCopied] = useState(false)
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
      setRevealedVotes([])
      setRoom(current => current ? {
        ...current,
        state: 'VOTING',
        version: startedRound.version,
        participants: current.participants.map(participant => ({ ...participant, has_voted: false })),
      } : current)
    }
    if (message.type === 'round.revealed') { const reveal = payload as Reveal; setRevealedVotes(reveal.revealed_votes); void api.getHistory(code).then(setHistory); if (token) void api.getSessionSummary(code, token).then(setSummary); setRound(reveal.round); setRoom(current => current ? { ...current, state: 'REVEALED', version: reveal.round.version } : current) }
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
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2400)
    return () => window.clearTimeout(timer)
  }, [notice])
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
  async function copyInviteLink() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setNotice('Ссылка скопирована')
      window.setTimeout(() => setCopied(false), 1400)
    } catch {
      setError('Не удалось скопировать ссылку')
    }
  }
  async function createNewSession() {
    try {
      if (!room || !self) return
      const session = await api.createRoom(`${room.name} — новая сессия`, self.display_name, { kind: room.deck.kind, cards: room.deck.kind === 'custom' ? room.deck.cards : undefined })
      if (!session.participant_token) throw new Error('Не удалось получить токен новой сессии')
      sessionStore.set(session.room.code, { token: session.participant_token, participantId: session.participant.id })
      window.location.assign(`/room/${session.room.code}`)
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Не удалось создать новую сессию')
    }
  }
  useEffect(() => {
    document.querySelectorAll<HTMLSpanElement>('.history-row > span').forEach((element, index) => {
      const item = history[index]
      if (item?.task_title) element.textContent = item.task_title
    })
  }, [history, room?.version])
  if (loading) return <main className="center">Загружаем комнату…</main>
  if (!room) return <main className="center"><p role="alert">{error || 'Комната не найдена'}</p><a href="/">На главную</a></main>
  if (!token || !self) return <main className="join-page"><section><span className="eyebrow">Приглашение в комнату</span><h1>{room.name}</h1><p>Введите имя, чтобы присоединиться к оценке.</p><form onSubmit={join}><label>Ваше имя<input value={joinName} onChange={e => setJoinName(e.target.value)} required autoFocus /></label>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary">Войти в комнату</button></form></section></main>

  const isOwner = self.is_owner
  async function exportTasks() {
    try {
      const file = await api.exportTasks(code, token!)
      const url = URL.createObjectURL(file)
      const link = document.createElement('a')
      link.href = url
      link.download = `scrum-planning-${code}.xlsx`
      link.click()
      URL.revokeObjectURL(url)
      setNotice('Excel-файл сформирован')
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Не удалось выгрузить задачи')
    }
  }
  const canEstimate = isOwner || room.estimate_editor_participant_id === self.id
  return <main className="room-shell"><header className="room-header"><a className="brand" href="/">PP</a><div><span className="eyebrow">Комната</span><h1>{room.name}</h1></div><div className="connection" aria-label="Статус соединения"><i className={status} />{status === 'connected' ? 'В сети' : 'Переподключение'}</div><button className="secondary export-link" onClick={() => void exportTasks()}>Выгрузить Excel</button><button className={`secondary copy-link${copied ? ' copied' : ''}`} onClick={copyInviteLink}>{copied ? '✓ Скопировано' : 'Скопировать ссылку'}</button></header>{error && <p className="toast" role="alert">{error}</p>}{notice && <p className="toast success-toast" role="status">✓ {notice}</p>}<div className="room-grid"><aside className="sidebar"><section className="panel"><h2>Участники <span>{room.participants.length}</span></h2><ul className="participants">{room.participants.map(p => <li key={p.id}><i className={p.is_online ? 'online' : 'offline'} /><span>{p.display_name}{p.is_owner && ' · владелец'}</span>{room.state === 'VOTING' && p.has_voted && <b aria-label="Проголосовал">✓</b>}</li>)}</ul><button type="button" className="secondary rename-self" onClick={() => { const name = window.prompt('Ваше имя', self.display_name); if (name?.trim() && name.trim() !== self.display_name) void action(() => api.renameSelf(room.code, name, token)) }}>Изменить моё имя</button></section>{isOwner && <ObserverModePanel room={room} token={token} observer={self.is_observer} onAction={action} />}<TaskList room={room} token={token} canManage={isOwner} canAdd={canEstimate} canEstimate={canEstimate} onAction={action} />{isOwner && <JiraPanel room={room} token={token} onAction={action} />}{isOwner && <EstimateAccessPanel room={room} token={token} onAction={action} />}{isOwner && <RoomSettings room={room} token={token} onError={setError} onUpdated={setRoom} />}</aside><section className="game"><RoundPanel key={round?.id ?? room.state} room={room} round={round} self={self} token={token} onAction={action} onError={setError} onReveal={reveal => { setRevealedVotes(reveal.revealed_votes); void api.getHistory(code).then(setHistory); void api.getSessionSummary(code, token).then(setSummary) }} onCreateSession={createNewSession} revealedVotes={revealedVotes.length ? revealedVotes : (history.find(item => item.id === round?.id)?.revealed_votes ?? [])} /><section className="panel history"><h2>История оценок</h2>{history.length ? history.map(item => <div className="history-row" key={item.id}><span>Задача {item.sequence}{item.task_title ? ` · ${item.task_title}` : ''}</span><strong>{item.revealed_votes.map(v => v.card_value).join(' · ')}</strong><small>{String(item.metrics.vote_count ?? 0)} голосов · среднее {item.metrics.mean === null ? '—' : String(item.metrics.mean)} · согласие {item.metrics.agreement_index === null ? '—' : `${Math.round(Number(item.metrics.agreement_index) * 100)}%`}</small></div>) : <p className="muted">Раскрытые оценки появятся здесь.</p>}<SessionSummaryPanel summary={summary} /></section></section></div>{room.state !== 'FINISHED' && <button className="finish" onClick={() => action(() => api.finish(code, room.version, token))}>Завершить сессию</button>}</main>
}

function ObserverModePanel({ room, token, observer, onAction }: { room: Room; token: string; observer: boolean; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  return <section className="panel observer-mode"><h2>Режим администратора</h2><div><button type="button" className={!observer ? 'primary active-mode' : 'secondary'} onClick={() => void onAction(() => api.setObserverMode(room.code, false, room.version, token))}>Голосую</button><button type="button" className={observer ? 'primary active-mode' : 'secondary'} onClick={() => void onAction(() => api.setObserverMode(room.code, true, room.version, token))}>Наблюдаю</button></div><p className="muted">Наблюдатель управляет оценкой, но не получает колоду.</p></section>
}

function EstimateAccessPanel({ room, token, onAction }: { room: Room; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  return <section className="panel estimate-access"><h2>Итоговая оценка</h2><label>Кто может её указать<select value={room.estimate_editor_participant_id ?? ''} onChange={event => void onAction(() => api.setEstimateEditor(room.code, event.target.value || null, room.version, token))}><option value="">Только я</option>{room.participants.filter(participant => !participant.is_owner).map(participant => <option key={participant.id} value={participant.id}>{participant.display_name}</option>)}</select></label><p className="muted">Выбранный участник сможет вручную сохранить итог после reveal.</p></section>
}

function SessionSummaryPanel({ summary }: { summary: SessionSummary | null }) {
  if (!summary || !summary.revealed_round_count) return null
  return <div className="session-summary"><h3>Сводка сессии</h3><p>{summary.revealed_round_count} оценок задач · {summary.total_vote_count} голосов · точное согласие: {summary.exact_consensus_count}</p><p>Средний индекс согласия: {summary.mean_agreement_index === null ? '—' : `${Math.round(summary.mean_agreement_index * 100)}%`}</p><p>Распределение: {Object.entries(summary.distribution).map(([value, count]) => `${value}: ${count}`).join(' · ') || 'нет числовых голосов'}</p>{Object.keys(summary.special_cards).length > 0 && <p>Служебные карты: {Object.entries(summary.special_cards).map(([value, count]) => `${value}: ${count}`).join(' · ')}</p>}</div>
}

function JiraPanel({ room, token, onAction }: { room: Room; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [baseUrl, setBaseUrl] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [jql, setJql] = useState('project = YOUR_PROJECT ORDER BY created DESC')
  const [issues, setIssues] = useState<JiraIssue[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const connection = { base_url: baseUrl, api_token: apiToken }
  const request = { connection, jql, start_at: 0, max_results: 25 }
  async function checkConnection() {
    try { setBusy(true); setStatus(''); await api.testJiraConnection(room.code, { connection }, token); setStatus('Подключение к Jira установлено') } catch (error) { setStatus(error instanceof Error ? error.message : 'Подключение не удалось') } finally { setBusy(false) }
  }
  async function preview() {
    try { setBusy(true); setStatus(''); const result = await api.previewJira(room.code, request, token); setIssues(result.issues); setSelected(result.issues.map(issue => issue.key)); setStatus(`Найдено задач: ${result.total}`) } catch (error) { setStatus(error instanceof Error ? error.message : 'Не удалось получить задачи') } finally { setBusy(false) }
  }
  return <section className="panel jira"><h2>Импорт из Jira</h2><label>Адрес Jira<input type="url" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://company.atlassian.net" /></label><label>API token<input type="password" value={apiToken} onChange={event => setApiToken(event.target.value)} autoComplete="off" /></label><div className="jira-actions"><button type="button" className="secondary" disabled={busy || !baseUrl || !apiToken} onClick={() => void checkConnection()}>{busy ? 'Проверяем…' : 'Проверить подключение'}</button></div>{status && <p className="jira-status" role="status">{status}</p>}<label>JQL-запрос<textarea value={jql} onChange={event => setJql(event.target.value)} rows={3} /></label><button type="button" className="secondary" disabled={busy || !baseUrl || !apiToken || !jql} onClick={() => void preview()}>Получить список задач</button>{issues.length > 0 && <><ul className="jira-issues">{issues.map(issue => <li key={issue.key}><label><input type="checkbox" checked={selected.includes(issue.key)} onChange={() => setSelected(current => current.includes(issue.key) ? current.filter(key => key !== issue.key) : [...current, issue.key])} /><span><strong>{issue.key}</strong>{issue.title}</span></label></li>)}</ul><button type="button" className="primary" disabled={busy || !selected.length} onClick={() => void onAction(async () => { await api.importJira(room.code, { ...request, expected_version: room.version, selected_keys: selected }, token); setIssues([]); setSelected([]); setApiToken(''); setStatus('Задачи добавлены в список оценки') })}>Добавить выбранные в задачи</button></>}<p className="muted">Токен используется только для запроса и не сохраняется.</p></section>
}

function TaskList({ room, token, canManage, canAdd, canEstimate, onAction }: { room: Room; token: string; canManage: boolean; canAdd: boolean; canEstimate: boolean; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [title, setTitle] = useState('')
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null)
  const tasks = [...room.tasks].sort((left, right) => left.position - right.position)
  const activeTask = tasks.find(task => task.id === room.active_task_id)
  useEffect(() => {
    document.querySelectorAll<HTMLButtonElement>('.tasks .task-title').forEach(button => {
      button.disabled = room.state === 'VOTING'
    })
  }, [room.state, tasks])
  const reorder = (targetTask: Task) => {
    if (!draggedTaskId || targetTask.is_locked || draggedTaskId === targetTask.id) return
    const source = tasks.find(task => task.id === draggedTaskId)
    if (!source || source.is_locked) return
    const ordered = [...tasks]
    const sourceIndex = ordered.findIndex(task => task.id === source.id)
    const targetIndex = ordered.findIndex(task => task.id === targetTask.id)
    if (ordered.slice(Math.min(sourceIndex, targetIndex), Math.max(sourceIndex, targetIndex) + 1).some(task => task.is_locked)) return
    ordered.splice(sourceIndex, 1)
    ordered.splice(targetIndex, 0, source)
    setDraggedTaskId(null)
    void onAction(() => api.reorderTasks(room.code, ordered.map(item => item.id), room.version, token))
  }
  const rename = (task: Task) => {
    const nextTitle = window.prompt('Новое название задачи', task.title)
    if (!nextTitle?.trim() || nextTitle.trim() === task.title) return
    void onAction(() => api.updateTask(room.code, task.id, nextTitle, room.version, token))
  }
  const remove = (task: Task) => {
    if (!window.confirm(`Удалить задачу «${task.title}»?`)) return
    void onAction(() => api.deleteTask(room.code, task.id, room.version, token))
  }
  return <section className="panel tasks"><div className="tasks-heading"><h2>Задачи</h2><span>{tasks.length}</span></div>{activeTask && <p className="active-task">Сейчас оцениваем <strong>{activeTask.title}</strong></p>}{canManage && <p className="task-drag-hint">Перетаскивайте задачи мышью, чтобы изменить порядок.</p>}<ol className="task-list">{tasks.map((task, index) => <li key={task.id} className={`${task.id === room.active_task_id ? 'active ' : ''}${canManage && !task.is_locked ? 'draggable ' : ''}${draggedTaskId === task.id ? 'dragging' : ''}`} draggable={canManage && !task.is_locked} onDragStart={() => setDraggedTaskId(task.id)} onDragEnd={() => setDraggedTaskId(null)} onDragOver={event => { if (draggedTaskId && !task.is_locked) event.preventDefault() }} onDrop={() => reorder(task)}><div className="task-row"><button type="button" className="task-title" onClick={() => void onAction(() => api.setActiveTask(room.code, task.id, room.version, token))}><span className="task-index">{index + 1}</span><span>{task.title}</span></button>{canAdd && <div className="task-actions"><button type="button" aria-label={`Переименовать ${task.title}`} title="Переименовать" onClick={() => rename(task)}>✎</button><button type="button" aria-label={`Удалить ${task.title}`} title={task.is_locked ? 'Задачу с голосами удалить нельзя' : 'Удалить'} disabled={task.is_locked} onClick={() => remove(task)}>×</button></div>}</div>{task.is_locked && !canEstimate && <small className="task-locked">Голоса получены · позиция зафиксирована</small>}{task.final_estimate && <p className="final-estimate">Итог: <strong>{task.final_estimate}</strong></p>}{canEstimate && <TaskEstimate key={`${task.id}:${task.final_estimate ?? ''}`} task={task} room={room} token={token} onAction={onAction} />}</li>)}</ol>{canAdd && <form className="task-form" onSubmit={event => { event.preventDefault(); if (!title.trim()) return; void onAction(async () => { await api.createTask(room.code, title, room.version, token); setTitle('') }) }}><input value={title} onChange={event => setTitle(event.target.value)} placeholder="Добавить задачу" maxLength={500} /><button className="secondary" type="submit">Добавить</button></form>}{!tasks.length && <p className="muted">Добавьте задачу вручную или импортируйте из Jira.</p>}</section>
}

function TaskEstimate({ task, room, token, onAction }: { task: Task; room: Room; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(task.final_estimate ?? '')
  if (!editing) return <button type="button" className="secondary estimate-toggle" onClick={() => setEditing(true)}>{task.final_estimate ? 'Изменить итог' : 'Указать итог'}</button>
  return <form className="final-estimate-form" onSubmit={event => { event.preventDefault(); if (!value.trim()) return; void onAction(() => api.setFinalEstimate(room.code, task.id, value, room.version, token)).then(() => setEditing(false)) }}><input autoFocus aria-label={`Итоговая оценка: ${task.title}`} placeholder="Итоговая оценка" value={value} onChange={event => setValue(event.target.value)} maxLength={32} /><button type="submit" className="secondary">Сохранить</button><button type="button" className="secondary" onClick={() => { setValue(task.final_estimate ?? ''); setEditing(false) }}>Отмена</button></form>
}

function EstimateCardModal({ cards, taskId, room, token, onAction, onClose }: { cards: Card[]; taskId: string; room: Room; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void>; onClose: () => void }) {
  const [selected, setSelected] = useState<string | null>(null)
  return <div className="estimate-modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><section className="estimate-modal" role="dialog" aria-modal="true" aria-labelledby="estimate-modal-title"><button type="button" className="modal-close" aria-label="Закрыть" onClick={onClose}>×</button><span className="eyebrow">Итоговая оценка</span><h2 id="estimate-modal-title">Выберите карту</h2><div className="cards estimate-cards" role="group" aria-label="Колода итоговой оценки">{cards.map(card => <button type="button" className={`card${selected === card.value ? ' selected' : ''}`} aria-pressed={selected === card.value} key={card.value} onClick={() => setSelected(card.value)}><span>{card.value}</span></button>)}</div><div className="vote-actions"><button type="button" className="secondary" onClick={onClose}>Отмена</button><button type="button" className="primary" disabled={!selected} onClick={() => { if (selected) void onAction(() => api.setFinalEstimate(room.code, taskId, selected, room.version, token)).then(onClose) }}>Подтвердить оценку</button></div></section></div>
}

function RoomSettings({ room, token, onError, onUpdated }: { room: Room; token: string; onError: (v: string) => void; onUpdated: (v: Room) => void }) { return <button type="button" className="room-name-edit" title="Редактировать название комнаты" aria-label="Редактировать название комнаты" onClick={() => { const name = window.prompt('Название комнаты', room.name); if (name?.trim() && name.trim() !== room.name) api.updateRoom(room.code, room.version, { name }, token).then(onUpdated).catch(error => onError(error.message)) }}>✎</button> }

function VotingTable({ room, revealedVotes = [] }: { room: Room; revealedVotes?: Array<{ display_name: string; card_value: string }> }) {
  const voters = room.participants.filter(participant => !participant.is_observer)
  const votesByName = new Map(revealedVotes.map(vote => [vote.display_name, vote.card_value]))
  const voted = revealedVotes.length || voters.filter(participant => participant.has_voted).length
  const revealed = revealedVotes.length > 0
  return <section className="poker-table" aria-label="Игральный стол"><header><span>Игральный стол</span><strong>{revealed ? 'Оценки раскрыты' : `${voted} из ${voters.length} проголосовали`}</strong></header><div className="table-felt"><div className="table-cards">{voters.map(participant => { const value = votesByName.get(participant.display_name); return <div className="table-seat" key={participant.id}><div className={`table-card${participant.has_voted || value ? ' dealt' : ''}${value ? ' card-face-up' : ''}`} aria-label={value ? `${participant.display_name}: ${value}` : participant.has_voted ? `${participant.display_name} проголосовал` : `${participant.display_name} наблюдает`}><span>{value ?? ''}</span></div><small>{participant.display_name}</small></div> })}</div></div></section>
}

function RoundPanel({ room, round, self, token, onAction, onError, onReveal, onCreateSession, revealedVotes = [] }: { room: Room; round: Round | null; self: { id: string; is_owner: boolean; is_observer: boolean; has_voted: boolean }; token: string; onAction: (fn: () => Promise<unknown>) => Promise<void>; onError: (v: string) => void; onReveal: (v: Reveal) => void; onCreateSession: () => Promise<void>; revealedVotes?: Array<{ display_name: string; card_value: string }> }) {
  const [selectedCard, setSelectedCard] = useState<{ roundId: string; value: string } | null>(null)
  const [estimatePickerOpen, setEstimatePickerOpen] = useState(false)
  const [revealMetrics, setRevealMetrics] = useState<Record<string, unknown> | null>(null)
  const selectedValue =
    selectedCard !== null && selectedCard.roundId === round?.id ? selectedCard.value : null
  const code = room.code
  const selectedTask = round?.task_id ? room.tasks.find(task => task.id === round?.task_id) : null
  useEffect(() => { if (room.state === 'REVEALED' && round) void api.getHistory(code).then(items => setRevealMetrics(items.find(item => item.id === round.id)?.metrics ?? null)) }, [code, room.state, round])
  const taskTitle = selectedTask?.title ?? (round ? `Задача ${round.sequence}` : '')
  if (room.state === 'REVEALED' && round) {
    const canSetEstimate = self.is_owner || room.estimate_editor_participant_id === self.id
    return <section className="panel results-panel">
      <span className="eyebrow">{taskTitle}</span>
      <h2>Оценки раскрыты</h2>
      <VotingTable room={room} revealedVotes={revealedVotes} />
      <RevealStats metrics={revealMetrics} />
      <div className="result-actions">
        {canSetEstimate && round.task_id && <button className="secondary set-estimate-button" onClick={() => setEstimatePickerOpen(true)}>Выбрать итоговую оценку</button>}
        <button className="secondary repeat-round-button" onClick={() => onAction(() => api.repeatRound(code, round.id, room.version, token))}>Повторное голосование</button>
      </div>
      <button className="primary" onClick={() => onAction(() => api.newRound(code, round.id, room.version, token))}>Следующая задача</button>
      {estimatePickerOpen && round.task_id && <EstimateCardModal cards={room.deck.cards} taskId={round.task_id} room={room} token={token} onAction={onAction} onClose={() => setEstimatePickerOpen(false)} />}
    </section>
  }
  if (room.state === 'VOTING' && round) return <VotingPanel room={room} round={round} self={self} token={token} selectedValue={selectedValue} taskTitle={taskTitle} onSelect={setSelectedCard} onAction={onAction} onError={onError} onReveal={reveal => { setRevealMetrics(reveal.metrics); onReveal(reveal) }} />
  if (room.state === 'FINISHED') return <section className="panel finished"><h2>Сессия завершена</h2><p>Комната доступна только для просмотра.</p><button className="primary" onClick={() => void onCreateSession()}>Создать новую сессию</button></section>
  if (room.state === 'LOBBY') return <section className="panel lobby"><span className="eyebrow">Лобби</span><h2>Готовы начать оценку?</h2><p>Любой подключённый участник может запустить оценку задачи.</p><button className="primary" onClick={() => onAction(() => api.startRound(code, room.version, token))}>Начать голосование</button></section>
  if (room.state === 'REVEALED' && round) { const canSetEstimate = self.is_owner || room.estimate_editor_participant_id === self.id; return <section className="panel results-panel"><span className="eyebrow">Задача {round.sequence}</span><h2>Оценки раскрыты</h2><VotingTable room={room} revealedVotes={revealedVotes} /><RevealStats metrics={revealMetrics} /><div className="result-actions">{canSetEstimate && round.task_id && <button className="secondary set-estimate-button" onClick={() => setEstimatePickerOpen(true)}>Выбрать итоговую оценку</button>}<button className="secondary repeat-round-button" onClick={() => onAction(() => api.repeatRound(code, round.id, room.version, token))}>Повторное голосование</button></div><button className="primary" onClick={() => onAction(() => api.newRound(code, round.id, room.version, token))}>Следующая задача</button>{estimatePickerOpen && round.task_id && <EstimateCardModal cards={room.deck.cards} taskId={round.task_id} room={room} token={token} onAction={onAction} onClose={() => setEstimatePickerOpen(false)} />}</section> }
  if (!round) return <section className="panel lobby"><span className="eyebrow">Синхронизация</span><h2>Подключаем задачу…</h2><p>Состояние комнаты обновляется автоматически.</p><button className="secondary" onClick={() => onAction(() => api.getSnapshot(code))}>Синхронизировать сейчас</button></section>
  return <section className="panel voting"><div className="round-top"><div><span className="eyebrow">Задача {round?.sequence ?? ''}</span><h2>Выберите карту</h2></div><button className="secondary" onClick={() => round && onAction(async () => { const reveal = await api.reveal(code, round.id, room.version, token); setRevealMetrics(reveal.metrics); onReveal(reveal) })}>Раскрыть карты</button></div><VotingTable room={room} />{self.is_observer ? <p className="muted">Вы наблюдаете за голосованием. Переключите режим администратора на «Голосую», чтобы получить колоду.</p> : self.has_voted ? <div className="confirmed-vote"><p className="vote-confirmation">Ваш выбор подтверждён. Карта лежит на столе рубашкой вверх.</p><button className="secondary" disabled={!round} onClick={() => round && onAction(() => api.cancelVote(code, round.id, token))}>Изменить голос</button></div> : <><div className="cards" role="group" aria-label="Колода">{room.deck.cards.map(card => <button className={`card${selectedValue === card.value ? ' selected' : ''}`} aria-pressed={selectedValue === card.value} key={card.value} onClick={() => round && setSelectedCard({ roundId: round.id, value: card.value })}><span>{card.value}</span></button>)}</div><div className="vote-actions"><button className="secondary" disabled={!selectedValue} onClick={() => setSelectedCard(null)}>Отменить выбор</button><button className="primary" disabled={!selectedValue || !round} onClick={() => round ? onAction(() => api.vote(code, round.id, selectedValue, token)) : onError('Задача не найдена')}>Подтвердить выбор</button></div><p className="vote-confirmation" aria-live="polite">{selectedValue ? `Выбрано: ${selectedValue}. Подтвердите выбор.` : 'Выберите карту — её значение останется скрытым.'}</p></>}<p className="muted">Значения карт раскроются одновременно.</p></section>
}

function VotingPanel({ room, round, self, token, selectedValue, taskTitle, onSelect, onAction, onError, onReveal }: { room: Room; round: Round; self: { is_observer: boolean; has_voted: boolean }; token: string; selectedValue: string | null; taskTitle: string; onSelect: (value: { roundId: string; value: string } | null) => void; onAction: (fn: () => Promise<unknown>) => Promise<void>; onError: (value: string) => void; onReveal: (reveal: Reveal) => void }) {
  const code = room.code
  return <section className="panel voting">
    <div className="round-top">
      <div><span className="eyebrow">{taskTitle}</span><h2>Выберите карту</h2></div>
      <button className="secondary" onClick={() => void onAction(async () => onReveal(await api.reveal(code, round.id, room.version, token)))}>Раскрыть карты</button>
    </div>
    <VotingTable room={room} />
    {self.is_observer ? <p className="muted">Вы наблюдаете за голосованием. Переключите режим администратора на «Голосую», чтобы получить колоду.</p> : self.has_voted ? <div className="confirmed-vote"><p className="vote-confirmation">Ваш выбор подтверждён. Карта лежит на столе рубашкой вверх.</p><button className="secondary" onClick={() => void onAction(() => api.cancelVote(code, round.id, token))}>Изменить голос</button></div> : <>
      <div className="cards" role="group" aria-label="Колода">{room.deck.cards.map(card => <button className={`card${selectedValue === card.value ? ' selected' : ''}`} aria-pressed={selectedValue === card.value} key={card.value} onClick={() => onSelect({ roundId: round.id, value: card.value })}><span>{card.value}</span></button>)}</div>
      <div className="vote-actions"><button className="secondary" disabled={!selectedValue} onClick={() => onSelect(null)}>Отменить выбор</button><button className="primary" disabled={!selectedValue} onClick={() => selectedValue ? void onAction(() => api.vote(code, round.id, selectedValue, token)) : onError('Задача не найдена')}>Подтвердить выбор</button></div>
      <p className="vote-confirmation" aria-live="polite">{selectedValue ? `Выбрано: ${selectedValue}. Подтвердите выбор.` : 'Выберите карту — её значение останется скрытым.'}</p>
    </>}
    <p className="muted">Значения карт раскроются одновременно.</p>
  </section>
}

function RevealStats({ metrics }: { metrics: Record<string, unknown> | null }) {
  if (!metrics) return null
  const distribution = metrics.distribution as Record<string, number> | undefined
  const special = metrics.special_cards as Record<string, number> | undefined
  const cards = [...Object.entries(distribution ?? {}), ...Object.entries(special ?? {})]
  const mean = metrics.mean as number | null
  const agreement = Math.round(Number(metrics.agreement_index ?? 0) * 100)
  return <section className="reveal-stats"><div className="stat-distribution"><div className="stat-cards">{cards.length ? cards.map(([value, count]) => <div className="stat-card" key={value}><b>{count}</b><i>{value}</i></div>) : '—'}</div></div><div className="stat-value"><span>Среднее</span><strong>{mean === null ? '—' : Number(mean).toFixed(1)}</strong></div><div className="agreement-stat"><i style={{ '--agreement': `${agreement}%` } as CSSProperties} /><span>Согласие {agreement}%</span></div></section>
}
