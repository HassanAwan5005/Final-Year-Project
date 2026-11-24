import { Ionicons } from '@expo/vector-icons';
import React, { useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import type { AdminBookingFilters } from '../../../api/services/admin.api';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { useDebounce } from '../../../hooks/useDebounce';
import { colors, spacing, typography } from '../../../theme';
import type { AdminBooking, BookingStatus } from '../../../types/models';
import { formatDate, formatPKR, formatStart } from '../../../utils/format';
import { StatusPill } from '../../bookings/components/StatusPill';
import { AdminHeader, adminStyles, Card, FilterChips, SearchBox } from '../components/AdminUI';
import { useAdminBookings } from '../hooks/useAdmin';

type StatusFilter = BookingStatus | 'ALL';

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'ACCEPTED', label: 'Accepted' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'CANCELLED', label: 'Cancelled' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'EXPIRED', label: 'Expired' },
];

/** Every booking on the platform. Search by reference or either party. */
export function AdminBookingsScreen({ onOpenBooking }: { onOpenBooking: (id: number) => void }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StatusFilter>('ALL');
  const q = useDebounce(search, 400);

  const filters = useMemo<AdminBookingFilters>(
    () => ({ q: q.trim() || undefined, status: status === 'ALL' ? undefined : status }),
    [q, status],
  );
  const bookings = useAdminBookings(filters);
  const rows = bookings.data?.pages.flatMap((page) => page.items) ?? [];
  const total = bookings.data?.pages[0]?.totalItems;

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader
        title="Bookings"
        subtitle={total !== undefined ? `${total.toLocaleString('en-PK')} matching` : 'All bookings'}
      />
      <SearchBox value={search} onChangeText={setSearch} placeholder="Reference (SNP-…), name or email" />
      <FilterChips options={FILTERS} value={status} onChange={setStatus} />

      {bookings.isLoading ? (
        <LoadingState label="Loading bookings…" />
      ) : bookings.isError ? (
        <ErrorState message={(bookings.error as ApiError)?.message} onRetry={() => bookings.refetch()} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={rows.length ? adminStyles.list : adminStyles.listEmpty}
          refreshControl={
            <RefreshControl
              refreshing={bookings.isRefetching && !bookings.isFetchingNextPage}
              onRefresh={() => {
                bookings.refetch();
              }}
              tintColor={colors.gold}
            />
          }
          onEndReached={() => {
            if (bookings.hasNextPage && !bookings.isFetchingNextPage) bookings.fetchNextPage();
          }}
          onEndReachedThreshold={0.4}
          ListFooterComponent={
            bookings.isFetchingNextPage ? (
              <ActivityIndicator color={colors.gold} style={adminStyles.footer} />
            ) : undefined
          }
          ListEmptyComponent={
            <EmptyState icon="calendar-outline" title="No bookings found" detail="Try another search or filter." />
          }
          renderItem={({ item }) => <BookingRow booking={item} onPress={() => onOpenBooking(item.id)} />}
        />
      )}
    </SafeAreaView>
  );
}

function BookingRow({ booking, onPress }: { booking: AdminBooking; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={`Open ${booking.reference}`}>
      <Card>
        <View style={styles.top}>
          <Text style={styles.reference}>{booking.reference}</Text>
          <StatusPill status={booking.status} label={booking.status_label} size="sm" />
        </View>
        <Text style={styles.service} numberOfLines={1}>
          {booking.service_title}
        </Text>
        <Text style={styles.people} numberOfLines={1}>
          {booking.buyer_name} → {booking.photographer_name}
        </Text>
        <View style={styles.bottom}>
          <Text style={styles.meta}>
            {formatDate(booking.event_date)} · {formatStart(booking)}
            {booking.location_city ? ` · ${booking.location_city}` : ''}
          </Text>
          <Text style={styles.price}>{formatPKR(booking.total_price)}</Text>
        </View>
        <Ionicons name="chevron-forward" size={16} color={colors.dim} style={styles.chevron} />
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  reference: { ...typography.caption, color: colors.gold, fontWeight: '600' },
  service: { ...typography.bodyBold, color: colors.text, marginTop: 2, paddingRight: spacing.xl },
  people: { ...typography.caption, color: colors.sub },
  bottom: { flexDirection: 'row', justifyContent: 'space-between', marginTop: spacing.xs },
  meta: { ...typography.tiny, color: colors.sub, flexShrink: 1 },
  price: { ...typography.caption, color: colors.text, fontWeight: '600' },
  chevron: { position: 'absolute', right: spacing.md, top: '50%' },
});
