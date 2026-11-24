import React, { useState } from 'react';
import { Alert, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { Avatar } from '../../../components/ui/Avatar';
import { Button } from '../../../components/ui/Button';
import { useAuthStore } from '../../../store/authStore';
import { colors, spacing, typography } from '../../../theme';
import { formatDate, formatPKR, timeAgo } from '../../../utils/format';
import {
  AdminHeader,
  adminStyles,
  Card,
  InfoRow,
  ReasonModal,
  SectionTitle,
  Tag,
} from '../components/AdminUI';
import { useAdminUser, useBlockUser, useUnblockUser } from '../hooks/useAdmin';
import { ROLE_LABEL } from './AdminUsersScreen';

/**
 * One account: details, cross-app numbers, and block / unblock.
 *
 * Blocking is done by the server in one step: the account is locked, every
 * session is signed out immediately, open bookings are cancelled through the
 * booking rules, and the action is written to the audit log.
 */
export function AdminUserDetailScreen({ userId, onBack }: { userId: number; onBack: () => void }) {
  const query = useAdminUser(userId);
  const block = useBlockUser();
  const unblock = useUnblockUser();
  const myId = useAuthStore((s) => s.user?.id);
  const [blocking, setBlocking] = useState(false);
  const [unblocking, setUnblocking] = useState(false);

  if (query.isLoading) {
    return (
      <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
        <AdminHeader title="User" onBack={onBack} />
        <LoadingState label="Loading user…" />
      </SafeAreaView>
    );
  }
  if (query.isError || !query.data) {
    return (
      <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
        <AdminHeader title="User" onBack={onBack} />
        <ErrorState message={(query.error as ApiError)?.message} onRetry={() => query.refetch()} />
      </SafeAreaView>
    );
  }

  const user = query.data;
  const { stats } = user;
  const canBlock = user.role !== 'ADMIN' && user.id !== myId;

  const fail = (title: string) => (error: unknown) =>
    Alert.alert(title, (error as ApiError)?.message ?? 'Please try again.');

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader title={user.full_name || user.email} onBack={onBack} />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching}
            onRefresh={() => {
              query.refetch();
            }}
            tintColor={colors.gold}
          />
        }
      >
        <Card style={styles.profile}>
          <Avatar uri={null} name={user.full_name} size={56} />
          <View style={styles.profileBody}>
            <Text style={styles.name}>{user.full_name || '—'}</Text>
            <Text style={styles.email}>{user.email}</Text>
            <View style={styles.tags}>
              <Tag label={ROLE_LABEL[user.role] ?? user.role} tone={user.role === 'ADMIN' ? 'gold' : 'neutral'} />
              {user.is_blocked ? <Tag label="Blocked" tone="red" /> : <Tag label="Active" tone="green" />}
              <Tag
                label={user.is_email_verified ? 'Email verified' : 'Email not verified'}
                tone={user.is_email_verified ? 'blue' : 'amber'}
              />
            </View>
          </View>
        </Card>

        {user.is_blocked && user.blocked_reason ? (
          <Card style={styles.blockedCard}>
            <Text style={styles.blockedTitle}>Blocked</Text>
            <Text style={styles.blockedReason}>{user.blocked_reason}</Text>
          </Card>
        ) : null}

        <SectionTitle>Account</SectionTitle>
        <Card>
          <InfoRow label="Phone" value={user.phone} />
          <InfoRow label="City" value={user.city} />
          <InfoRow label="Joined" value={formatDate(user.joined_at)} />
          <InfoRow label="Last login" value={user.last_login ? timeAgo(user.last_login) : 'Never'} />
          {user.role === 'PHOTOGRAPHER' ? (
            <InfoRow
              label="Photographer profile"
              value={user.is_approved_photographer ? 'Listed' : 'Not listed'}
            />
          ) : null}
        </Card>

        <SectionTitle>Activity</SectionTitle>
        <Card>
          {user.role === 'PHOTOGRAPHER' ? (
            <>
              <InfoRow label="Bookings received" value={stats.bookings_received} />
              <InfoRow label="Shoots delivered" value={stats.shoots_delivered} />
            </>
          ) : (
            <>
              <InfoRow label="Bookings made" value={stats.bookings_made} />
              <InfoRow label="Completed" value={stats.bookings_completed} />
              <InfoRow label="Cancelled" value={stats.bookings_cancelled} />
              <InfoRow label="Total spent" value={formatPKR(stats.total_spent)} />
              <InfoRow label="Reviews written" value={stats.reviews_written} />
            </>
          )}
        </Card>

        {canBlock ? (
          <View style={styles.actions}>
            {user.is_blocked ? (
              <Button
                label="Unblock account"
                onPress={() => setUnblocking(true)}
                loading={unblock.isPending}
              />
            ) : (
              <>
                <Button
                  label="Block account"
                  variant="danger"
                  onPress={() => setBlocking(true)}
                  loading={block.isPending}
                />
                <Text style={styles.note}>
                  Blocking signs the user out everywhere and cancels their open bookings.
                </Text>
              </>
            )}
          </View>
        ) : (
          <Text style={[styles.note, styles.actions]}>
            {user.id === myId
              ? 'This is your own account.'
              : 'Administrator accounts cannot be blocked from the app.'}
          </Text>
        )}
      </ScrollView>

      <ReasonModal
        visible={blocking}
        title="Block this account?"
        detail={`${user.full_name} (${user.email})`}
        label="Reason (shown to the user and stored in the audit log)"
        placeholder="e.g. Repeated fake bookings reported by photographers."
        confirmLabel="Block"
        danger
        loading={block.isPending}
        onCancel={() => setBlocking(false)}
        onConfirm={(reason) =>
          block.mutate(
            { id: user.id, reason },
            {
              onSuccess: () => {
                setBlocking(false);
                Alert.alert('Account blocked', 'The user has been signed out everywhere.');
              },
              onError: fail('Could not block'),
            },
          )
        }
      />

      <ReasonModal
        visible={unblocking}
        title="Unblock this account?"
        detail={`${user.full_name} (${user.email})`}
        label="Note (optional, stored in the audit log)"
        placeholder="e.g. Issue resolved with the user."
        confirmLabel="Unblock"
        optional
        minLength={3}
        loading={unblock.isPending}
        onCancel={() => setUnblocking(false)}
        onConfirm={(reason) =>
          unblock.mutate(
            { id: user.id, reason },
            {
              onSuccess: () => setUnblocking(false),
              onError: fail('Could not unblock'),
            },
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge },
  profile: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg },
  profileBody: { flex: 1, gap: 2 },
  name: { ...typography.h3, color: colors.text },
  email: { ...typography.caption, color: colors.sub },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs },
  blockedCard: { marginTop: spacing.md, borderColor: colors.red },
  blockedTitle: { ...typography.bodyBold, color: colors.red },
  blockedReason: { ...typography.caption, color: colors.text },
  actions: { marginTop: spacing.xl, gap: spacing.sm },
  note: { ...typography.caption, color: colors.sub, textAlign: 'center' },
});
