import { Ionicons } from '@expo/vector-icons';
import React, { useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import type { AdminUserFilters } from '../../../api/services/admin.api';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { Avatar } from '../../../components/ui/Avatar';
import { useDebounce } from '../../../hooks/useDebounce';
import { colors, spacing, typography } from '../../../theme';
import type { AdminUser } from '../../../types/models';
import { formatDate } from '../../../utils/format';
import { AdminHeader, adminStyles, Card, FilterChips, SearchBox, Tag } from '../components/AdminUI';
import { useAdminUsers } from '../hooks/useAdmin';

type UserFilter = 'ALL' | 'BUYER' | 'PHOTOGRAPHER' | 'ADMIN' | 'BLOCKED';

const FILTERS: { value: UserFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'BUYER', label: 'Buyers' },
  { value: 'PHOTOGRAPHER', label: 'Photographers' },
  { value: 'ADMIN', label: 'Admins' },
  { value: 'BLOCKED', label: 'Blocked' },
];

export const ROLE_LABEL: Record<AdminUser['role'], string> = {
  BUYER: 'Buyer',
  PHOTOGRAPHER: 'Photographer',
  ADMIN: 'Admin',
};

/** Search by name or email, filter by role or blocked, tap to open a user. */
export function AdminUsersScreen({ onOpenUser }: { onOpenUser: (id: number) => void }) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<UserFilter>('ALL');
  const q = useDebounce(search, 400);

  const filters = useMemo<AdminUserFilters>(
    () => ({
      q: q.trim() || undefined,
      role: filter === 'ALL' || filter === 'BLOCKED' ? undefined : filter,
      blocked: filter === 'BLOCKED' ? true : undefined,
    }),
    [q, filter],
  );
  const users = useAdminUsers(filters);
  const rows = users.data?.pages.flatMap((page) => page.items) ?? [];
  const total = users.data?.pages[0]?.totalItems;

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader
        title="Users"
        subtitle={total !== undefined ? `${total} matching` : 'Search and manage accounts'}
      />
      <SearchBox value={search} onChangeText={setSearch} placeholder="Search name or email" />
      <FilterChips options={FILTERS} value={filter} onChange={setFilter} />

      {users.isLoading ? (
        <LoadingState label="Loading users…" />
      ) : users.isError ? (
        <ErrorState message={(users.error as ApiError)?.message} onRetry={() => users.refetch()} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={rows.length ? adminStyles.list : adminStyles.listEmpty}
          refreshControl={
            <RefreshControl
              refreshing={users.isRefetching && !users.isFetchingNextPage}
              onRefresh={() => {
                users.refetch();
              }}
              tintColor={colors.gold}
            />
          }
          onEndReached={() => {
            if (users.hasNextPage && !users.isFetchingNextPage) users.fetchNextPage();
          }}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            users.isFetchingNextPage ? (
              <ActivityIndicator color={colors.gold} style={adminStyles.footer} />
            ) : undefined
          }
          ListEmptyComponent={
            <EmptyState icon="people-outline" title="No users found" detail="Try another search or filter." />
          }
          renderItem={({ item }) => <UserRow user={item} onPress={() => onOpenUser(item.id)} />}
        />
      )}
    </SafeAreaView>
  );
}

function UserRow({ user, onPress }: { user: AdminUser; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={`Open ${user.full_name}`}>
      <Card style={styles.row}>
        <Avatar uri={null} name={user.full_name} size={40} />
        <View style={styles.body}>
          <Text style={styles.name} numberOfLines={1}>
            {user.full_name || user.email}
          </Text>
          <Text style={styles.email} numberOfLines={1}>
            {user.email}
          </Text>
          <View style={styles.tags}>
            <Tag label={ROLE_LABEL[user.role] ?? user.role} tone={user.role === 'ADMIN' ? 'gold' : 'neutral'} />
            {user.is_blocked ? <Tag label="Blocked" tone="red" /> : null}
            {!user.is_email_verified ? <Tag label="Unverified" tone="amber" /> : null}
            <Text style={styles.joined}>Joined {formatDate(user.joined_at)}</Text>
          </View>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.sub} />
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  body: { flex: 1, gap: 2 },
  name: { ...typography.bodyBold, color: colors.text },
  email: { ...typography.caption, color: colors.sub },
  tags: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.xs, marginTop: 4 },
  joined: { ...typography.tiny, color: colors.dim },
});
