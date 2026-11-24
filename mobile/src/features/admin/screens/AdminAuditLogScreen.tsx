import React, { useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { colors, spacing, typography } from '../../../theme';
import type { AuditEntry } from '../../../types/models';
import { formatDate, timeAgo } from '../../../utils/format';
import { AdminHeader, adminStyles, Card, FilterChips, Tag } from '../components/AdminUI';
import { useAuditLog } from '../hooks/useAdmin';

const ACTION_LABEL: Record<string, string> = {
  USER_BLOCKED: 'User blocked',
  USER_UNBLOCKED: 'User unblocked',
  USER_DELETED: 'User deleted',
  PHOTOGRAPHER_APPROVED: 'Photographer approved',
  PHOTOGRAPHER_REJECTED: 'Photographer rejected',
  BOOKING_FORCE_CANCELLED: 'Booking force-cancelled',
  PRODUCT_APPROVED: 'Ad approved',
  PRODUCT_REMOVED: 'Ad removed',
  REVIEW_HIDDEN: 'Review hidden',
  WALLET_ADJUSTED: 'Wallet adjusted',
  TOPUP_APPROVED: 'Top-up approved',
  TOPUP_REJECTED: 'Top-up rejected',
  SETTING_CHANGED: 'Setting changed',
  CATEGORY_CHANGED: 'Category changed',
  BROADCAST_SENT: 'Broadcast sent',
  MODEL_PROMOTED: 'ML model promoted',
};

type ActionFilter =
  | 'ALL'
  | 'USER_BLOCKED'
  | 'USER_UNBLOCKED'
  | 'BOOKING_FORCE_CANCELLED'
  | 'PRODUCT_REMOVED'
  | 'REVIEW_HIDDEN'
  | 'SETTING_CHANGED'
  | 'BROADCAST_SENT';

const FILTERS: { value: ActionFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'USER_BLOCKED', label: 'Blocks' },
  { value: 'USER_UNBLOCKED', label: 'Unblocks' },
  { value: 'BOOKING_FORCE_CANCELLED', label: 'Cancellations' },
  { value: 'PRODUCT_REMOVED', label: 'Ads removed' },
  { value: 'REVIEW_HIDDEN', label: 'Reviews hidden' },
  { value: 'SETTING_CHANGED', label: 'Settings' },
  { value: 'BROADCAST_SENT', label: 'Broadcasts' },
];

const DANGER = new Set(['USER_BLOCKED', 'BOOKING_FORCE_CANCELLED', 'PRODUCT_REMOVED', 'REVIEW_HIDDEN', 'USER_DELETED']);

/** Read-only by design: the server has no route that edits or deletes a row. */
export function AdminAuditLogScreen({ onBack }: { onBack: () => void }) {
  const [action, setAction] = useState<ActionFilter>('ALL');
  const filters = useMemo(() => ({ action: action === 'ALL' ? undefined : action }), [action]);
  const log = useAuditLog(filters);
  const rows = log.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader title="Audit log" subtitle="Read-only record of every admin action" onBack={onBack} />
      <FilterChips options={FILTERS} value={action} onChange={setAction} />

      {log.isLoading ? (
        <LoadingState label="Loading audit log…" />
      ) : log.isError ? (
        <ErrorState message={(log.error as ApiError)?.message} onRetry={() => log.refetch()} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={rows.length ? adminStyles.list : adminStyles.listEmpty}
          refreshControl={
            <RefreshControl
              refreshing={log.isRefetching && !log.isFetchingNextPage}
              onRefresh={() => {
                log.refetch();
              }}
              tintColor={colors.gold}
            />
          }
          onEndReached={() => {
            if (log.hasNextPage && !log.isFetchingNextPage) log.fetchNextPage();
          }}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            log.isFetchingNextPage ? <ActivityIndicator color={colors.gold} style={adminStyles.footer} /> : undefined
          }
          ListEmptyComponent={
            <EmptyState icon="document-text-outline" title="No entries" detail="Admin actions will be listed here." />
          }
          renderItem={({ item }) => <AuditRow entry={item} />}
        />
      )}
    </SafeAreaView>
  );
}

function describeChanges(changes: Record<string, unknown>): string {
  return Object.entries(changes ?? {})
    .map(([key, value]) =>
      Array.isArray(value) && value.length === 2
        ? `${key}: ${String(value[0])} → ${String(value[1])}`
        : `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`,
    )
    .join('\n');
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const changes = describeChanges(entry.changes);
  return (
    <Card>
      <View style={styles.top}>
        <Tag label={ACTION_LABEL[entry.action] ?? entry.action} tone={DANGER.has(entry.action) ? 'red' : 'gold'} />
        <Text style={styles.when}>{timeAgo(entry.created_at)}</Text>
      </View>
      <Text style={styles.target} numberOfLines={2}>
        {entry.target_label || `${entry.target_type} #${entry.target_id ?? '—'}`}
      </Text>
      <Text style={styles.meta}>
        By {entry.actor_name} · {formatDate(entry.created_at)}
        {entry.ip_address ? ` · ${entry.ip_address}` : ''}
      </Text>
      {entry.reason ? <Text style={styles.reason}>“{entry.reason}”</Text> : null}
      {changes ? <Text style={styles.changes}>{changes}</Text> : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  when: { ...typography.tiny, color: colors.sub },
  target: { ...typography.bodyBold, color: colors.text, marginTop: spacing.xs },
  meta: { ...typography.tiny, color: colors.sub },
  reason: { ...typography.caption, color: colors.text, marginTop: 2 },
  changes: { ...typography.tiny, color: colors.sub, marginTop: 2 },
});
