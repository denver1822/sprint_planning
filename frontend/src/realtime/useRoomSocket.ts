import { useCallback, useEffect, useRef, useState } from 'react'

export type RoomSocketStatus = 'connecting' | 'connected' | 'disconnected'

export interface RoomSocketMessage {
  type: string
  payload: unknown
}

interface UseRoomSocketOptions {
  roomCode: string | null
  participantToken: string | null
  onMessage: (message: RoomSocketMessage) => void
}

export function useRoomSocket({
  roomCode,
  participantToken,
  onMessage,
}: UseRoomSocketOptions) {
  const [status, setStatus] = useState<RoomSocketStatus>('disconnected')
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef(0)
  const onMessageRef = useRef(onMessage)

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!roomCode || !participantToken) {
      return
    }

    let disposed = false
    let reconnectTimer: number | undefined

    const connect = () => {
      setStatus('connecting')
      const url = new URL(`/ws/rooms/${encodeURIComponent(roomCode)}`, window.location.origin)
      url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      url.searchParams.set('participant_token', participantToken)

      const socket = new WebSocket(url)
      socketRef.current = socket

      socket.onopen = () => {
        reconnectAttemptRef.current = 0
        setStatus('connected')
      }
      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          onMessageRef.current(JSON.parse(event.data) as RoomSocketMessage)
        } catch {
          // Ignore malformed frames; the server remains the source of truth.
        }
      }
      socket.onclose = () => {
        if (disposed) {
          return
        }
        setStatus('disconnected')
        const delay = Math.min(1_000 * 2 ** reconnectAttemptRef.current, 10_000)
        reconnectAttemptRef.current += 1
        reconnectTimer = window.setTimeout(connect, delay)
      }
    }

    connect()
    return () => {
      disposed = true
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer)
      }
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [participantToken, roomCode])

  const requestResync = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'resync' }))
    }
  }, [])

  return { status, requestResync }
}
