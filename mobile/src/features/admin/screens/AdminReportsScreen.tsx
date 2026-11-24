import { Ionicons } from '@expo/vector-icons';
import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import type { AdminFlagFilters } from '../../../api/services/admin.api';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { Button } from '../../../components/ui/Button';
import { colors, spacing, typography } from '../../../theme';
import type { FlagContentType, FlagReason, FlagStatus, ModerationFlag } from '../../../types/models';
import { timeAgo } from '../../../utils/format';
import { AdminHeader, adminStyles, Card, FilterChips, ReasonModal, Tag } from '../components/AdminUI';
import { useAdminFlags, useClaimFlag, useResolveFlag } from '../hooks/useAdmin';

type StatusFilter = FlagStatus | 'ALL';
type KindFilter = 'PRODUCT' | 'REVIEW' | 'MESSAGE' | 'ALL';

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'OPEN', label: 'Open' },
  { value: 'REVIEWING', label: 'In review' },
  { value: 'ACTIONED', label: 'Actioned' },
  { value: 'DISMISSED', label: 'Dismissed' },
  { value: 'ALL', label: 'All' },
];

const KIND_FILTERS: { value: KindFilter; label: string }[] = [
  { value: 'ALL', label: 'Everything' },
  { value: 'PRODUCT', label: 'Ads' },
  { value: 'REVIEW', label: 'Reviews' },
  { value: 'MESSAGE', label: 'Chat messages' },
];

const KIND: Record<FlagContentType, { label: string; icon: keyof typeof Ionicons.glyphMap; takeDown: string }> = {
  PRODUCT: { label: 'Ad', icon: 'pricetag-outline', takeDown: 'Remove ad' },
  REVIEW: { label: 'Review', icon: 'star-outline', takeDown: 'Hide review' },
  MESSAGE: { label: 'Chat message', icon: 'chatbubble-outline', takeDown: 'Remove message' },
  PORTFOLIO_IMAGE: { label: 'Portfolio photo', icon: 'image-outline', takeDown: 'Remove photo' },
  PROFILE: { label: 'Profile', icon: 'person-outline', takeDown: 'Mark actioned' },
};

const REASON: Record<FlagReason, string> = {
  INAPPROPRIATE: 'Inappropriate content',
  COPYRIGHT: 'Copyright infringement',
  SPAM: 'Spam',
  FAKE: 'Fake or misleading',
  HARASSMENT: 'Harassment',
  OFF_PLATFORM: 'Taking the deal off-platform',
  OTHER: 'Other',
};

const STATUS_TONE: Record<FlagStatus, 'amber' | 'blue' | 'red' | 'neutral'> = {
  OPEN: 'amber',
  REVIEWING: 'blue',
  ACTIONED: 'red',
  DISMISSED: 'neutral',
};

const STATUS_LABEL: Record<FlagStatus, string> = {
  OPEN: 'Open',
  REVIEWING: 'In review',
  ACTIONED: 'Actioned',
  DISMISSED: 'Dismissed',
};

/**
 * One queue for everything users report. "Take down" resolves the report as
 * ACTIONED, which makes the server hide the review / remove the ad / redact
 * the message in the same step. "Dismiss" closes it and leaves the content.
 */
export function AdminReportsScreen() {
  const [status, setStatus] = useState<StatusFilter>('OPEN');
  const [kind, setKind] = useState<KindFilter>('ALL');
  const filters = useMemo<AdminFlagFilters>(
    () => ({
      status: status === 'ALL' ? undefined : status,
      content_type: kind === 'ALL' ? undefined : kind,
    }),
    [status, kind],
  );
  const flags = useAdminFlags(filters);
  const claim = useClaimFlag();
  const resolve = useResolveFlag();

  const [acting, setActing] = useState<{ flag: ModerationFlag; action: 'ACTIONED' | 'DISMISSED' } | null>(
    null,
  );

  const rows = flags.data?.pages.flatMap((page) => page.items) ?? [];
  const total = flags.data?.pages[0]?.totalItems;

  const fail = (title: string) => (error: unknown) =>
    Alert.alert(title, (error as ApiError)?.message ?? 'Please try again.');

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader
        title="Reports"
        subtitle={total !== undefined ? `${total} in this view` : 'Reported ads, reviews and messages'}
      />
      <FilterChips options={STATUS_FILTERS} value={status} onChange={setStatus} />
      <FilterChips options={KIND_FILTERS} value={kind} onChange={setKind} />

      {flags.isLoading ? (
        <LoadingState label="Loading reports…" />
      ) : flags.isError ? (
        <ErrorState message={(flags.error as ApiError)?.message} onRetry={() => flags.refetch()} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={rows.length ? adminStyles.list : adminStyles.listEmpty}
          refreshControl={
            <RefreshControl
              refreshing={flags.isRefetching && !flags.isFetchingNextPage}
              onRefresh={() => {
                flags.refetch();
              }}
              tintColor={colors.gold}
            />
          }
          onEndReached={() => {
            if (flags.hasNextPage && !flags.isFetchingNextPage) flags.fetchNextPage();
          }}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            flags.isFetchingNextPage ? (
              <ActivityIndicator color={colors.gold} style={adminStyles.footer} />
            ) : undefined
          }
          ListEmptyComponent={
            <EmptyState
              icon="checkmark-done-outline"
              title={status === 'OPEN' ? 'No open reports' : 'Nothing here'}
              detail="Reports from users about ads, reviews and chat messages appear here."
            />
          }
          renderItem={({ item }) => (
            <FlagCard
              flag={item}
              busy={
                (claim.isPending && claim.variables === item.id) ||
                (resolve.isPending && resolve.variables?.id === item.id)
              }
              onClaim={() => claim.mutate(item.id, { onError: fail('Could not claim') })}
              onTakeDown={() => setActing({ flag: item, action: 'ACTIONED' })}
              onDismiss={() => setActing({ flag: item, action: 'DISMISSED' })}
            />
          )}
        />
      )}

      <ReasonModal
        visible={acting !== null}
        title={
          acting?.action === 'ACTIONED'
            ? `${KIND[acting.flag.content_type]?.takeDown ?? 'Take action'}?`
            : 'Dismiss this report?'
        }
        detail={acting?.flag.target_preview}
        label={
          acting?.action === 'ACTIONED'
            ? 'What was done and why (sent to the owner, stored in the audit log)'
            : 'Note (optional)'
        }
        placeholder={
          acting?.action === 'ACTIONED'
            ? 'e.g. Ad uses stock photos — removed from the shop.'
            : 'e.g. Content does not break the rules.'
        }
        confirmLabel={acting?.action === 'ACTIONED' ? 'Take down' : 'Dismiss'}
        danger={acting?.action === 'ACTIONED'}
        optional={acting?.action === 'DISMISSED'}
        minLength={acting?.action === 'ACTIONED' ? 5 : 3}
        loading={resolve.isPending}
        onCancel={() => setActing(null)}
        onConfirm={(note) => {
          if (!acting) return;
          resolve.mutate(
            { id: acting.flag.id, action: acting.action, note },
            {
              onSuccess: () => setActing(null),
              onError: fail('Could not resolve'),
            },
          );
        }}
      />
    </SafeAreaView>
  );
}

function FlagCard({
  flag,
  busy,
  onClaim,
  onTakeDown,
  onDismiss,
}: {
  flag: ModerationFlag;
  busy: boolean;
  onClaim: () => void;
  onTakeDown: () => void;
  onDismiss: () => void;
}) {
  const kind = KIND[flag.content_type] ?? KIND.PROFILE;
  const resolved = flag.status === 'ACTIONED' || flag.status === 'DISMISSED';

  return (
    <Card>
      <View style={styles.top}>
        <View style={styles.kind}>
          <Ionicons name={kind.icon} size={16} color={colors.gold} />
          <Text style={styles.kindText}>{kind.label}</Text>
        </View>
        <Tag label={STATUS_LABEL[flag.status] ?? flag.status} tone={STATUS_TONE[flag.status] ?? 'neutral'} />
      </View>

      <Text style={styles.preview} numberOfLines={3}>
        {flag.target_preview || '—'}
      </Text>
      <Text style={styles.reason}>{REASON[flag.reason] ?? flag.reason}</Text>
      {flag.detail ? <Text style={styles.detail}>“{flag.detail}”</Text> : null}
      <Text style={styles.meta}>
        Reported by {flag.reporter_name ?? 'a user'} · {timeAgo(flag.created_at)}
      </Text>

      {resolved ? (
        <View style={styles.resolution}>
          <Text style={styles.meta}>
            {flag.status === 'ACTIONED' ? 'Actioned' : 'Dismissed'} by {flag.resolved_by_name ?? 'an admin'}
            {flag.resolved_at ? ` · ${timeAgo(flag.resolved_at)}` : ''}
          </Text>
          {flag.resolution_note ? <Text style={styles.detail}>{flag.resolution_note}</Text> : null}
        </View>
      ) : (
        <View style={styles.actions}>
          {flag.status === 'OPEN' ? (
            <View style={styles.flex}>
              <Button label="Claim" variant="ghost" size="sm" onPress={onClaim} disabled={busy} />
            </View>
          ) : null}
          <View style={styles.flex}>
            <Button label="Dismiss" variant="secondary" size="sm" onPress={onDismiss} disabled={busy} />
          </View>
          <View style={styles.flex}>
            <Button label={kind.takeDown} variant="danger" size="sm" onPress={onTakeDown} loading={busy} />
          </View>
        </View>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  kind: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  kindText: { ...typography.caption, color: colors.gold },
  preview: { ...typography.bodyBold, color: colors.text, marginTop: spacing.xs },
  reason: { ...typography.caption, color: colors.amber },
  detail: { ...typography.caption, color: colors.text },
  meta: { ...typography.tiny, color: colors.sub },
  resolution: { marginTop: spacing.sm, gap: 2 },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
});
