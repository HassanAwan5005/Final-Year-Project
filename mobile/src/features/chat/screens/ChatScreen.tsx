import { Ionicons } from '@expo/vector-icons';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { Avatar } from '../../../components/ui/Avatar';
import { useAuthStore } from '../../../store/authStore';
import { colors, radius, spacing, typography } from '../../../theme';
import { formatDate, formatPKR, timeAgo } from '../../../utils/format';
import type { Message } from '../../../types/models';
import {
  useChatThread,
  useConversation,
  useDeleteMessage,
  useDeleteMessageForMe,
  useReportMessage,
  useSmartReplies,
  useStartConversation,
  useToggleBlock,
} from '../hooks/useChat';

/**
 * One conversation.
 *
 * WHY THE LIST IS INVERTED
 * ------------------------
 * `inverted` renders index 0 at the bottom, which means a new message pushes the
 * thread up without a scroll animation, and opening the screen lands on the
 * newest message rather than scrolling there after paint. The rows are reversed
 * for rendering only — the data stays oldest-first, which is the order every
 * other part of the app uses.
 *
 * WHY "Reconnecting…" IS SHOWN
 * ----------------------------
 * The socket can drop on a network switch and the app keeps working — sends go
 * over HTTP and the reconnect replays what was missed. But a chat screen that
 * silently stops being live while looking live is worse than one that admits it,
 * because the user's next decision is whether to wait or call.
 */
export function ChatScreen({
  conversationId: initialConversationId,
  startWith,
  title,
  onBack,
  onOpenBooking,
  onOpenProduct,
}: {
  /** An existing thread. Pass 0 or null when only `startWith` is known. */
  conversationId?: number | null;
  /**
   * "Message this person" — used by the booking and product screens, which know
   * the other party's user id but not whether a thread exists. Resolving it here keeps the
   * idempotent open-or-find call in one place instead of in every caller.
   */
  startWith?: { userId: number; bookingId?: number; productId?: number };
  title?: string;
  onBack: () => void;
  onOpenBooking?: (bookingId: number) => void;
  onOpenProduct?: (slug: string) => void;
}) {
  const [resolvedId, setResolvedId] = useState<number | null>(
    initialConversationId && initialConversationId > 0 ? initialConversationId : null,
  );
  const start = useStartConversation();
  const startedRef = useRef(false);

  useEffect(() => {
    if (resolvedId || !startWith || startedRef.current) return;
    // Guarded with a ref, not just state: two renders before the mutation
    // resolves would otherwise fire it twice, and while the server collapses
    // that to one thread, the second request is pure waste.
    startedRef.current = true;
    start.mutate(
      {
        user: startWith.userId,
        booking: startWith.bookingId ?? null,
        product: startWith.productId ?? null,
      },
      {
        onSuccess: (thread) => setResolvedId(thread.id),
        onError: (error) =>
          Alert.alert(
            'Could not open the conversation',
            (error as ApiError).message,
            [{ text: 'Back', onPress: onBack }],
          ),
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedId, startWith]);

  if (!resolvedId) {
    return <LoadingState label="Opening conversation…" />;
  }
  return (
    <ChatThread
      conversationId={resolvedId}
      title={title}
      onBack={onBack}
      onOpenBooking={onOpenBooking}
      onOpenProduct={onOpenProduct}
    />
  );
}

function ChatThread({
  conversationId,
  title,
  onBack,
  onOpenBooking,
  onOpenProduct,
}: {
  conversationId: number;
  title?: string;
  onBack: () => void;
  onOpenBooking?: (bookingId: number) => void;
  onOpenProduct?: (slug: string) => void;
}) {
  const currentUser = useAuthStore((s) => s.user);
  const conversation = useConversation(conversationId);
  const thread = useChatThread(conversationId);
  const removeMessage = useDeleteMessage(conversationId);
  const removeForMe = useDeleteMessageForMe(conversationId);
  const report = useReportMessage();
  const toggleBlock = useToggleBlock();
  const smartReplies = useSmartReplies(conversationId);

  const [draft, setDraft] = useState('');
  const listRef = useRef<FlatList<Message>>(null);

  // Clearing the badge is a side effect of *reading*, so it fires when the
  // thread's newest id changes rather than on every render.
  const newestId = thread.messages.length
    ? thread.messages[thread.messages.length - 1].id
    : 0;
  useEffect(() => {
    if (newestId > 0) thread.markThreadRead();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newestId]);

  const other = conversation.data?.other_participant;
  const heading = title ?? other?.business_name ?? other?.full_name ?? 'Conversation';

  /** Reversed for the inverted list; the source order stays oldest-first. */
  const rows = useMemo(() => [...thread.messages].reverse(), [thread.messages]);

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    setDraft('');
    thread.send(text);
  };

  const messageOptions = (message: Message) => {
    const options: { text: string; style?: 'cancel' | 'destructive'; onPress?: () => void }[] =
      [];

    if (message.failed) {
      options.push({ text: 'Try sending again', onPress: () => thread.retryFailed(message) });
    }
    if (message.is_mine && message.id > 0 && !message.is_deleted) {
      options.push({
        text: 'Delete for everyone',
        style: 'destructive',
        onPress: () =>
          removeMessage.mutate(message.id, {
            onError: (error) =>
              Alert.alert('Could not delete', (error as ApiError).message),
          }),
      });
    }
    if (message.id > 0) {
      options.push({
        text: 'Delete for me',
        style: 'destructive',
        onPress: () =>
          removeForMe.mutate(message.id, {
            onError: (error) =>
              Alert.alert('Could not delete', (error as ApiError).message),
          }),
      });
    }
    if (!message.is_mine && message.id > 0) {
      options.push({
        text: 'Report this message',
        style: 'destructive',
        onPress: () =>
          report.mutate(
            { messageId: message.id, reason: 'INAPPROPRIATE' },
            {
              onSuccess: () =>
                Alert.alert('Reported', 'Our team will take a look at this thread.'),
              onError: (error) =>
                Alert.alert('Could not report', (error as ApiError).message),
            },
          ),
      });
    }
    if (!options.length) return;
    Alert.alert('Message', undefined, [...options, { text: 'Cancel', style: 'cancel' }]);
  };

  const threadOptions = () =>
    Alert.alert(heading, undefined, [
      {
        text: conversation.data?.is_blocked ? 'Unblock' : 'Block this person',
        style: conversation.data?.is_blocked ? 'default' : 'destructive',
        onPress: () => toggleBlock.mutate(conversationId),
      },
      { text: 'Cancel', style: 'cancel' },
    ]);

  if (thread.isLoading && !thread.messages.length) {
    return <LoadingState label="Opening conversation…" />;
  }
  if (thread.isError && !thread.messages.length) {
    return (
      <ErrorState
        message={(thread.error as ApiError)?.message}
        onRetry={() => thread.refetch()}
      />
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
        <View style={styles.avatarWrap}>
          <Avatar name={other?.full_name ?? heading} uri={other?.avatar_url} size={36} />
          {other?.is_online ? <View style={styles.onlineBadge} /> : null}
        </View>
        <View style={styles.headerBody}>
          <Text style={styles.title} numberOfLines={1}>
            {heading}
          </Text>
          <View style={styles.presenceRow}>
            {other?.is_online && thread.connected ? (
              <View style={styles.onlineDot} />
            ) : null}
            <Text
              style={[
                styles.presence,
                other?.is_online && thread.connected && styles.presenceOnline,
              ]}
              numberOfLines={1}
            >
              {!thread.connected
                ? 'Reconnecting…'
                : other?.is_online
                  ? 'Online'
                  : other?.last_seen_at
                    ? `Last seen ${timeAgo(other.last_seen_at)}`
                    : 'Offline'}
            </Text>
          </View>
        </View>
        <Pressable onPress={threadOptions} hitSlop={10} accessibilityLabel="Options">
          <Ionicons name="ellipsis-vertical" size={18} color={colors.sub} />
        </Pressable>
      </View>

      {conversation.data?.booking ? (
        <Pressable
          style={styles.bookingBar}
          onPress={() =>
            conversation.data?.booking && onOpenBooking?.(conversation.data.booking.id)
          }
          disabled={!onOpenBooking}
        >
          <Ionicons name="calendar-outline" size={15} color={colors.gold} />
          <Text style={styles.bookingText} numberOfLines={1}>
            {conversation.data.booking.service_title} ·{' '}
            {formatDate(conversation.data.booking.event_date)} ·{' '}
            {conversation.data.booking.status.toLowerCase()}
          </Text>
          {onOpenBooking ? (
            <Ionicons name="chevron-forward" size={15} color={colors.sub} />
          ) : null}
        </Pressable>
      ) : null}

      {conversation.data?.product ? (
        <Pressable
          style={styles.bookingBar}
          onPress={() =>
            conversation.data?.product && onOpenProduct?.(conversation.data.product.slug)
          }
          disabled={!onOpenProduct || !conversation.data.product.is_available}
        >
          <Ionicons name="pricetag-outline" size={15} color={colors.gold} />
          <Text style={styles.bookingText} numberOfLines={1}>
            {conversation.data.product.title} ·{' '}
            {conversation.data.product.is_available
              ? formatPKR(conversation.data.product.price)
              : 'not available right now'}
          </Text>
          {onOpenProduct && conversation.data.product.is_available ? (
            <Ionicons name="chevron-forward" size={15} color={colors.sub} />
          ) : null}
        </Pressable>
      ) : null}

      {conversation.data?.is_blocked ? (
        <View style={styles.blockedBar}>
          <Text style={styles.blockedText}>
            You blocked this person. You will not see new messages until you unblock them.
          </Text>
        </View>
      ) : null}

      <View style={styles.encryptionNotice}>
        <View style={styles.encryptionPill}>
          <Ionicons
            name="lock-closed"
            size={10}
            color={colors.gold}
            style={styles.encryptionIcon}
          />
          <Text style={styles.encryptionText}>Messages are stored securely</Text>
        </View>
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 8 : 0}
      >
        <FlatList
          ref={listRef}
          data={rows}
          inverted
          keyExtractor={(item) => item.client_id || String(item.id)}
          contentContainerStyle={styles.list}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <Bubble
              message={item}
              currentUserId={currentUser?.id}
              onLongPress={() => messageOptions(item)}
            />
          )}
          ListEmptyComponent={
            <View style={styles.emptyThread}>
              <Text style={styles.emptyTitle}>No messages yet</Text>
              <Text style={styles.emptyDetail}>
                {conversation.data?.product
                  ? 'Ask about the condition, the price or where to collect it.'
                  : 'Ask about a date, a location or what is included.'}
              </Text>
            </View>
          }
        />

        {smartReplies.data && smartReplies.data.length > 0 ? (
          <View style={styles.smartReplyBar}>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.smartReplyScroll}
              keyboardShouldPersistTaps="handled"
            >
              {smartReplies.data.map((item, idx) => (
                <Pressable
                  key={idx}
                  style={({ pressed }) => [
                    styles.smartReplyChip,
                    pressed && styles.smartReplyChipPressed,
                  ]}
                  onPress={() => {
                    thread.send(item.text);
                  }}
                  accessibilityRole="button"
                  accessibilityLabel={item.text}
                >
                  <Ionicons
                    name="sparkles"
                    size={12}
                    color={colors.gold}
                    style={{ marginRight: 6 }}
                  />
                  <Text style={styles.smartReplyText} numberOfLines={1}>
                    {item.text}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        ) : null}

        <View style={styles.composer}>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder="Write a message…"
            placeholderTextColor={colors.dim}
            multiline
            maxLength={5000}
            style={styles.input}
          />
          <Pressable
            onPress={send}
            disabled={!draft.trim()}
            style={[styles.sendButton, !draft.trim() && styles.sendButtonOff]}
            accessibilityRole="button"
            accessibilityLabel="Send message"
          >
            <Ionicons
              name="send"
              size={17}
              color={draft.trim() ? colors.bg : colors.dim}
            />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Bubble({
  message,
  currentUserId,
  onLongPress,
}: {
  message: Message;
  currentUserId?: number;
  onLongPress: () => void;
}) {
  const mine = Boolean(
    message.is_mine || (currentUserId && message.sender === currentUserId),
  );

  if (message.message_type === 'SYSTEM') {
    return <Text style={styles.system}>{message.body}</Text>;
  }

  return (
    <Pressable
      onLongPress={onLongPress}
      style={[styles.bubbleRow, mine ? styles.bubbleRowMine : styles.bubbleRowTheirs]}
    >
      <View style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleTheirs]}>
        <Text style={[styles.bubbleText, message.is_deleted && styles.bubbleDeleted]}>
          {message.body}
        </Text>
        <View style={styles.bubbleMeta}>
          {message.is_edited ? <Text style={styles.metaText}>edited</Text> : null}
          <Text style={styles.metaText}>
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </Text>
          {mine ? (
            <Ionicons
              // Three honest states: in flight, failed, delivered — and a
              // second tick only once the other side has actually read it.
              name={
                message.failed
                  ? 'alert-circle-outline'
                  : message.pending
                    ? 'time-outline'
                    : message.read_at
                      ? 'checkmark-done'
                      : 'checkmark'
              }
              size={13}
              color={
                message.failed
                  ? colors.red
                  : message.read_at
                    ? colors.blue
                    : colors.sub
              }
            />
          ) : null}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  avatarWrap: {
    position: 'relative',
  },
  onlineBadge: {
    position: 'absolute',
    right: -1,
    bottom: -1,
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.green,
    borderWidth: 2,
    borderColor: colors.bg,
  },
  headerBody: { flex: 1 },
  title: { ...typography.h3, color: colors.text },
  presenceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  onlineDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.green,
  },
  presence: { ...typography.tiny, color: colors.sub },
  presenceOnline: {
    color: colors.green,
    fontWeight: '600',
  },
  bookingBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  bookingText: { ...typography.tiny, color: colors.text, flex: 1 },
  blockedBar: { backgroundColor: colors.redDim, padding: spacing.md },
  blockedText: { ...typography.tiny, color: colors.text, textAlign: 'center' },
  list: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.lg,
    flexGrow: 1,
    justifyContent: 'flex-end',
  },
  bubbleRow: {
    width: '100%',
    flexDirection: 'row',
    marginBottom: spacing.sm,
  },
  bubbleRowMine: {
    justifyContent: 'flex-end',
    alignSelf: 'flex-end',
  },
  bubbleRowTheirs: {
    justifyContent: 'flex-start',
    alignSelf: 'flex-start',
  },
  bubble: {
    maxWidth: '82%',
    borderRadius: radius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  bubbleMine: {
    backgroundColor: colors.goldDim,
    borderBottomRightRadius: radius.sm,
    alignSelf: 'flex-end',
  },
  bubbleTheirs: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderBottomLeftRadius: radius.sm,
    alignSelf: 'flex-start',
  },
  bubbleText: { ...typography.body, color: colors.text, lineHeight: 20 },
  bubbleDeleted: { color: colors.dim, fontStyle: 'italic' },
  bubbleMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: spacing.xs,
    marginTop: 2,
  },
  metaText: { ...typography.tiny, color: colors.sub, fontSize: 10 },
  system: {
    ...typography.tiny,
    color: colors.dim,
    textAlign: 'center',
    marginVertical: spacing.md,
  },
  emptyThread: {
    alignItems: 'center',
    paddingVertical: spacing.huge,
    // No transform here. The inverted list already flips its empty component
    // back the right way on each platform (scale -1 on Android, scaleY -1 on
    // iOS). A transform here REPLACES that correction, which left the text
    // mirrored left-to-right on Android.
  },
  emptyTitle: { ...typography.h3, color: colors.text },
  emptyDetail: {
    ...typography.caption,
    color: colors.sub,
    marginTop: spacing.xs,
    textAlign: 'center',
  },
  encryptionNotice: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    backgroundColor: 'transparent',
  },
  encryptionPill: {
    // Pin this English label to LTR so an RTL device locale cannot flip the
    // lock icon to the wrong side or mirror the row.
    direction: 'ltr',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  encryptionIcon: {
    marginRight: 6,
  },
  encryptionText: {
    ...typography.tiny,
    color: colors.dim,
    fontSize: 11,
    fontWeight: '500',
    textAlign: 'left',
    writingDirection: 'ltr',
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  input: {
    ...typography.body,
    color: colors.text,
    flex: 1,
    maxHeight: 120,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  sendButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.gold,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonOff: { backgroundColor: colors.card },
  smartReplyBar: {
    paddingVertical: spacing.xs,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  smartReplyScroll: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  smartReplyChip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
    maxWidth: 320,
  },
  smartReplyChipPressed: {
    backgroundColor: colors.border,
    opacity: 0.85,
  },
  smartReplyText: {
    ...typography.caption,
    color: colors.text,
    fontSize: 12,
  },
});
