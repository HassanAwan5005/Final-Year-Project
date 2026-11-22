/**
 * React Query hooks for chat — Module 13.
 *
 * THE SOCKET IS AN ACCELERATOR, NOT THE SOURCE OF TRUTH
 * ----------------------------------------------------
 * `useMessages` owns the thread cache and is filled from HTTP. The socket only
 * appends what it receives and, on reconnect, triggers a `?after=<last id>`
 * fetch that replays whatever it missed. Building the thread FROM socket frames
 * is how chat apps lose messages when a phone switches from Wi-Fi to data.
 *
 * SENDING IS OPTIMISTIC BUT RECONCILED BY `client_id`
 * -------------------------------------------------
 * The bubble appears instantly with a temporary negative id. When the POST
 * returns, the real row replaces it — matched on `client_id`, not on position,
 * because two quick sends can resolve out of order. A failed send leaves the
 * bubble marked `failed` rather than silently vanishing.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { tokenStorage } from '../../../api/client';
import { WS_ROUTES } from '../../../api/config';
import { qk } from '../../../api/queryKeys';
import { chatApi, messageClientId } from '../../../api/services/chat.api';
import { useAuthStore } from '../../../store/authStore';
import type {
  ChatParticipant,
  Conversation,
  ConversationDetail,
  Message,
} from '../../../types/models';

// ═══════════════════════════════════════════════════════════════════════════
// THREAD LIST
// ═══════════════════════════════════════════════════════════════════════════
export function useConversations(archived = false) {
  return useQuery({
    queryKey: qk.chat.conversations(archived),
    queryFn: () => chatApi.conversations({ archived }),
    staleTime: 20_000,
    refetchOnWindowFocus: true,
  });
}

export function useConversation(id: number | null) {
  return useQuery({
    queryKey: qk.chat.conversation(id ?? 0),
    queryFn: () => chatApi.detail(id!),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}

export function useChatUnreadTotal() {
  return useQuery({
    queryKey: qk.chat.unread,
    queryFn: () => chatApi.unreadTotal(),
    staleTime: 20_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}

export function useStartConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      user: number;
      booking?: number | null;
      product?: number | null;
      message?: string;
    }) => chatApi.start(payload),
    // Idempotent server-side, so a double-tap is safe — but the list ordering
    // and the badge both moved.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.chat.all }),
    retry: false,
  });
}

export function useChatContacts(term = '') {
  return useQuery({
    queryKey: qk.chat.contacts(term),
    queryFn: () => chatApi.contacts(term),
    staleTime: 60_000,
  });
}

export function useSmartReplies(conversationId: number | null) {
  return useQuery({
    queryKey: ['chat', 'smart-replies', conversationId],
    queryFn: () => (conversationId ? chatApi.smartReplies(conversationId) : Promise.resolve([])),
    enabled: Boolean(conversationId),
    staleTime: 5_000,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// PER-THREAD SETTINGS
// ═══════════════════════════════════════════════════════════════════════════
function useThreadToggle<T>(fn: (id: number) => Promise<T>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.chat.all }),
    retry: false,
  });
}

export function useToggleMute() {
  return useThreadToggle((id: number) => chatApi.toggleMute(id));
}

export function useToggleBlock() {
  return useThreadToggle((id: number) => chatApi.toggleBlock(id));
}

export function useToggleArchive() {
  return useThreadToggle((id: number) => chatApi.toggleArchive(id));
}

export function useLeaveConversation() {
  return useThreadToggle((id: number) => chatApi.leave(id));
}

export function useMarkThreadRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, upTo }: { id: number; upTo?: number }) =>
      chatApi.markRead(id, upTo),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.chat.conversations(false) });
      queryClient.invalidateQueries({ queryKey: qk.chat.unread });
    },
    retry: false,
  });
}

/** What a message looks like once deleted for everyone (same as the server's). */
function blanked(rows: Message[] | undefined, messageId: number) {
  return rows?.map((row) =>
    row.id === messageId
      ? { ...row, is_deleted: true, body: 'This message was deleted' }
      : row,
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// THE THREAD ITSELF
// ═══════════════════════════════════════════════════════════════════════════
export function useMessages(conversationId: number | null) {
  return useQuery({
    queryKey: qk.chat.messages(conversationId ?? 0),
    queryFn: () => chatApi.messages(conversationId!, { limit: 50 }),
    enabled: Boolean(conversationId),
    // The socket keeps this fresh while the screen is open; the fetch is for
    // opening it and for reconnecting.
    staleTime: 10_000,
  });
}

/**
 * The full send/receive loop for one open thread.
 *
 * Returns the message list to render (server rows plus any optimistic bubbles),
 * a `send` function, and the socket's connection state so the header can say
 * "reconnecting…" honestly instead of pretending everything is live.
 */
export function useChatThread(conversationId: number | null) {
  const queryClient = useQueryClient();
  const messages = useMessages(conversationId);
  const markRead = useMarkThreadRead();

  const [pending, setPending] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const key = qk.chat.messages(conversationId ?? 0);

  /** Merge a server row in, replacing its optimistic twin if there is one. */
  const absorb = useCallback(
    (incoming: Message) => {
      queryClient.setQueryData<Message[]>(key, (rows = []) => {
        if (rows.some((row) => row.id === incoming.id)) return rows;
        return [...rows, incoming];
      });
      if (incoming.client_id) {
        setPending((rows) => rows.filter((row) => row.client_id !== incoming.client_id));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [conversationId, queryClient],
  );

  // ─── Socket ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let reconnecting = false;

    const connect = async () => {
      const token = await tokenStorage.getAccess();
      if (!token || cancelled) return;

      try {
        const socket = new WebSocket(WS_ROUTES.chat(conversationId, token));
        socketRef.current = socket;

        socket.onopen = () => {
          if (cancelled) return;
          setConnected(true);
          // Replay whatever arrived while the socket was down. This is the
          // whole reason messages are addressed by id rather than by page.
          const rows = queryClient.getQueryData<Message[]>(key) ?? [];
          const lastId = rows.length ? rows[rows.length - 1].id : undefined;
          chatApi
            .messages(conversationId, { after: lastId, limit: 100 })
            .then((missed) => missed.forEach(absorb))
            .catch(() => undefined);
          // The replay only brings new messages. A message deleted for everyone
          // while the socket was down shows up by reloading the thread.
          if (reconnecting) queryClient.invalidateQueries({ queryKey: key });
          reconnecting = true;
        };

        socket.onmessage = (event) => {
          try {
            const frame = JSON.parse(event.data as string);
            if (frame.type === 'message') {
              const currentUserId = useAuthStore.getState().user?.id;
              const isMine = Boolean(
                frame.is_mine ?? (currentUserId && frame.sender_id === currentUserId),
              );
              absorb({
                id: frame.id,
                conversation: frame.conversation_id,
                sender: frame.sender_id,
                sender_name: frame.sender_name ?? '',
                sender_avatar: null,
                is_mine: isMine,
                message_type: frame.message_type ?? 'TEXT',
                body: frame.body ?? '',
                client_id: frame.client_id ?? '',
                is_edited: false,
                is_deleted: false,
                attachments: [],
                delivered_at: null,
                read_at: null,
                created_at: frame.created_at,
              });
              queryClient.invalidateQueries({ queryKey: qk.chat.unread });
            } else if (frame.type === 'message_deleted') {
              queryClient.setQueryData<Message[]>(key, (rows) => blanked(rows, frame.id));
              queryClient.invalidateQueries({ queryKey: qk.chat.conversations(false) });
            } else if (frame.type === 'presence' && frame.is_online) {
              // Only trust "online" from the thread socket. Its "offline" frame
              // fires when the other person merely leaves this screen while
              // still in the app — real offline comes from usePresenceSocket.
              queryClient.setQueryData<any>(qk.chat.conversation(conversationId), (old: any) => {
                if (!old?.other_participant || old.other_participant.id !== frame.user_id) return old;
                return {
                  ...old,
                  other_participant: {
                    ...old.other_participant,
                    is_online: Boolean(frame.is_online),
                    last_seen_at: frame.is_online ? old.other_participant.last_seen_at : new Date().toISOString(),
                  },
                };
              });
            }
          } catch {
            // A malformed frame is not worth breaking the screen over.
          }
        };

        socket.onclose = () => {
          setConnected(false);
          if (!cancelled) retry = setTimeout(connect, 5_000);
        };
        socket.onerror = () => socket.close();
      } catch {
        setConnected(false);
      }
    };

    connect();
    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
      socketRef.current?.close();
      socketRef.current = null;
      setConnected(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // ─── Sending ─────────────────────────────────────────────────────────────
  const send = useCallback(
    async (body: string) => {
      const text = body.trim();
      if (!conversationId || !text) return;

      const clientId = messageClientId();
      const optimistic: Message = {
        // A negative id can never collide with a server row, which makes
        // "is this bubble real yet?" a check rather than a guess.
        id: -Date.now(),
        conversation: conversationId,
        sender: -1,
        sender_name: '',
        sender_avatar: null,
        is_mine: true,
        message_type: 'TEXT',
        body: text,
        client_id: clientId,
        is_edited: false,
        is_deleted: false,
        attachments: [],
        delivered_at: null,
        read_at: null,
        created_at: new Date().toISOString(),
        pending: true,
      };
      setPending((rows) => [...rows, optimistic]);

      try {
        const saved = await chatApi.send(conversationId, text, clientId);
        absorb(saved);
        queryClient.invalidateQueries({ queryKey: qk.chat.conversations(false) });
      } catch {
        // Kept on screen and marked failed. Dropping it silently would look
        // like the message was sent.
        setPending((rows) =>
          rows.map((row) =>
            row.client_id === clientId ? { ...row, pending: false, failed: true } : row,
          ),
        );
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [conversationId, absorb, queryClient],
  );

  const retryFailed = useCallback(
    (message: Message) => {
      setPending((rows) => rows.filter((row) => row.client_id !== message.client_id));
      send(message.body);
    },
    [send],
  );

  const markThreadRead = useCallback(() => {
    if (!conversationId) return;
    const rows = queryClient.getQueryData<Message[]>(key) ?? [];
    const lastId = rows.length ? rows[rows.length - 1].id : undefined;
    if (lastId && lastId > 0) markRead.mutate({ id: conversationId, upTo: lastId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, queryClient]);

  const serverRows = messages.data ?? [];
  const pendingRows = pending.filter(
    (row) => !serverRows.some((saved) => saved.client_id && saved.client_id === row.client_id),
  );

  return {
    messages: [...serverRows, ...pendingRows],
    isLoading: messages.isLoading,
    isError: messages.isError,
    error: messages.error,
    refetch: messages.refetch,
    connected,
    send,
    retryFailed,
    markThreadRead,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// SINGLE MESSAGE ACTIONS
// ═══════════════════════════════════════════════════════════════════════════
/** Delete for everyone: both sides see "This message was deleted". */
export function useDeleteMessage(conversationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (messageId: number) => chatApi.remove(messageId),
    onSuccess: (_, messageId) => {
      const key = qk.chat.messages(conversationId ?? 0);
      queryClient.setQueryData<Message[]>(key, (rows) => blanked(rows, messageId));
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: qk.chat.conversations(false) });
    },
    retry: false,
  });
}

/** Delete for me: it disappears here and stays on the other side. */
export function useDeleteMessageForMe(conversationId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (messageId: number) => chatApi.removeForMe(messageId),
    onSuccess: (_, messageId) => {
      const key = qk.chat.messages(conversationId ?? 0);
      queryClient.setQueryData<Message[]>(key, (rows) =>
        rows?.filter((row) => row.id !== messageId),
      );
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: qk.chat.conversations(false) });
    },
    retry: false,
  });
}

export function useReportMessage() {
  return useMutation({
    mutationFn: ({
      messageId,
      reason,
      detail,
    }: {
      messageId: number;
      reason: string;
      detail?: string;
    }) => chatApi.report(messageId, reason, detail),
    retry: false,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// PRESENCE
// ═══════════════════════════════════════════════════════════════════════════

/** Keeps the backend's 60s presence TTL alive with margin. */
const PRESENCE_HEARTBEAT_MS = 30_000;

/**
 * One presence socket for the whole signed-in app.
 *
 * The backend reports `is_online` from a Redis key that ONLY /ws/presence/
 * sets (and expires after 60s without a heartbeat). Without this socket every
 * user is reported offline. Incoming presence frames are patched straight into
 * the cached conversation detail and list rows so dots update live.
 */
export function usePresenceSocket(enabled: boolean) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let heartbeat: ReturnType<typeof setInterval> | undefined;

    const applyPresence = (userId: number, isOnline: boolean) => {
      const patch = (p: ChatParticipant | null) =>
        p && p.id === userId
          ? {
              ...p,
              is_online: isOnline,
              last_seen_at: isOnline ? p.last_seen_at : new Date().toISOString(),
            }
          : p;

      queryClient.setQueriesData<ConversationDetail>(
        { queryKey: ['chat', 'conversation'] },
        (old) =>
          old && old.other_participant?.id === userId
            ? { ...old, other_participant: patch(old.other_participant) }
            : old,
      );
      queryClient.setQueriesData<unknown>(
        { queryKey: ['chat', 'conversations'] },
        (old: unknown) => {
          const patchRow = (row: Conversation) =>
            row.other_participant?.id === userId
              ? { ...row, other_participant: patch(row.other_participant) }
              : row;
          if (Array.isArray(old)) return old.map(patchRow);
          const page = old as { results?: Conversation[] } | undefined;
          if (page && Array.isArray(page.results)) {
            return { ...page, results: page.results.map(patchRow) };
          }
          return old;
        },
      );
    };

    const connect = async () => {
      const token = await tokenStorage.getAccess();
      if (!token || cancelled) return;

      try {
        socket = new WebSocket(WS_ROUTES.presence(token));
        socket.onopen = () => {
          if (heartbeat) clearInterval(heartbeat);
          heartbeat = setInterval(() => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'heartbeat' }));
            }
          }, PRESENCE_HEARTBEAT_MS);
        };
        socket.onmessage = (event) => {
          try {
            const frame = JSON.parse(event.data as string);
            if (frame.type === 'presence' && typeof frame.user_id === 'number') {
              applyPresence(frame.user_id, Boolean(frame.is_online));
            }
          } catch {
            // Ignore malformed frames.
          }
        };
        socket.onclose = () => {
          if (heartbeat) clearInterval(heartbeat);
          if (!cancelled) retry = setTimeout(connect, 15_000);
        };
        socket.onerror = () => socket?.close();
      } catch {
        // Presence is cosmetic; never surface a socket failure to the user.
      }
    };

    connect();
    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
      if (heartbeat) clearInterval(heartbeat);
      socket?.close();
      socket = null;
    };
  }, [enabled, queryClient]);
}
