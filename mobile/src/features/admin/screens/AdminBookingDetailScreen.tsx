import React, { useState } from 'react';
import { Alert, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { Button } from '../../../components/ui/Button';
import { colors, spacing, typography } from '../../../theme';
import { formatDate, formatDuration, formatPKR, formatStart, timeAgo } from '../../../utils/format';
import { StatusPill } from '../../bookings/components/StatusPill';
import { AdminHeader, adminStyles, Card, InfoRow, ReasonModal, SectionTitle } from '../components/AdminUI';
import { useAdminBooking, useForceCancelBooking } from '../hooks/useAdmin';

/**
 * One booking, read-only, plus Force cancel.
 *
 * Force cancel goes through the booking state machine on the server: only a
 * Pending or Accepted booking can be cancelled, both people are notified with
 * the reason, the timeline gets a row and the audit log records it.
 */
export function AdminBookingDetailScreen({
  bookingId,
  onBack,
  onOpenUser,
}: {
  bookingId: number;
  onBack: () => void;
  onOpenUser: (id: number) => void;
}) {
  const query = useAdminBooking(bookingId);
  const forceCancel = useForceCancelBooking();
  const [cancelling, setCancelling] = useState(false);

  if (query.isLoading) {
    return (
      <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
        <AdminHeader title="Booking" onBack={onBack} />
        <LoadingState label="Loading booking…" />
      </SafeAreaView>
    );
  }
  if (query.isError || !query.data) {
    return (
      <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
        <AdminHeader title="Booking" onBack={onBack} />
        <ErrorState message={(query.error as ApiError)?.message} onRetry={() => query.refetch()} />
      </SafeAreaView>
    );
  }

  const booking = query.data;

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader title={booking.reference} onBack={onBack} />
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
        <Card>
          <View style={styles.top}>
            <Text style={styles.service}>{booking.service_title}</Text>
            <StatusPill status={booking.status} label={booking.status_label} />
          </View>
          {booking.category ? <Text style={styles.sub}>{booking.category}</Text> : null}
          <InfoRow label="Date" value={formatDate(booking.event_date)} />
          <InfoRow label="Start" value={formatStart(booking)} />
          <InfoRow label="Length" value={formatDuration(booking.duration_hours)} />
          <InfoRow label="City" value={booking.location_city} />
          <InfoRow label="Address" value={booking.location_address} />
          <InfoRow label="Requested" value={timeAgo(booking.created_at)} />
        </Card>

        <SectionTitle>People</SectionTitle>
        <Card>
          <PersonRow
            role="Buyer"
            name={booking.buyer_name}
            email={booking.buyer_email}
            onPress={() => onOpenUser(booking.buyer_id)}
          />
          <View style={styles.divider} />
          <PersonRow
            role="Photographer"
            name={booking.photographer_name}
            email={booking.photographer_email}
            onPress={() => onOpenUser(booking.photographer_user_id)}
          />
        </Card>

        <SectionTitle>Price</SectionTitle>
        <Card>
          <InfoRow label="Service" value={formatPKR(booking.unit_price)} />
          {Number(booking.travel_fee) > 0 ? (
            <InfoRow label="Travel fee" value={formatPKR(booking.travel_fee)} />
          ) : null}
          {Number(booking.discount) > 0 ? (
            <InfoRow label="Discount" value={`− ${formatPKR(booking.discount)}`} />
          ) : null}
          <InfoRow label="Total" value={formatPKR(booking.total_price)} />
          <InfoRow label="Platform commission" value={formatPKR(booking.commission_amount)} />
          <InfoRow label="Photographer payout" value={formatPKR(booking.photographer_payout)} />
        </Card>

        {booking.notes || booking.special_requirements ? (
          <>
            <SectionTitle>Notes from the buyer</SectionTitle>
            <Card>
              {booking.notes ? <Text style={styles.body}>{booking.notes}</Text> : null}
              {booking.special_requirements ? (
                <Text style={styles.body}>{booking.special_requirements}</Text>
              ) : null}
            </Card>
          </>
        ) : null}

        {booking.rejection_reason || booking.cancellation_note || booking.cancelled_by_name ? (
          <>
            <SectionTitle>Outcome</SectionTitle>
            <Card>
              <InfoRow label="Rejection reason" value={booking.rejection_reason} />
              <InfoRow label="Cancelled by" value={booking.cancelled_by_name} />
              <InfoRow label="Cancellation note" value={booking.cancellation_note} />
            </Card>
          </>
        ) : null}

        <SectionTitle>Timeline</SectionTitle>
        <Card>
          {booking.history.length ? (
            booking.history.map((step, index) => (
              <View key={`${step.created_at}-${index}`} style={styles.step}>
                <View style={styles.dot} />
                <View style={styles.stepBody}>
                  <Text style={styles.stepTitle}>
                    {step.from_status ? `${step.from_status} → ${step.to_status}` : step.to_status}
                  </Text>
                  <Text style={styles.stepMeta}>
                    {step.changed_by_name}
                    {step.actor_role ? ` (${step.actor_role.toLowerCase()})` : ''} · {timeAgo(step.created_at)}
                  </Text>
                  {step.note ? <Text style={styles.stepNote}>{step.note}</Text> : null}
                </View>
              </View>
            ))
          ) : (
            <Text style={styles.sub}>No status changes recorded.</Text>
          )}
        </Card>

        <View style={styles.actions}>
          {booking.can_force_cancel ? (
            <>
              <Button
                label="Force cancel booking"
                variant="danger"
                onPress={() => setCancelling(true)}
                loading={forceCancel.isPending}
              />
              <Text style={styles.note}>Both the buyer and the photographer are told the reason.</Text>
            </>
          ) : (
            <Text style={styles.note}>
              This booking is {booking.status_label.toLowerCase()} and can no longer be cancelled.
            </Text>
          )}
        </View>
      </ScrollView>

      <ReasonModal
        visible={cancelling}
        title="Force cancel this booking?"
        detail={`${booking.reference} · ${booking.buyer_name} → ${booking.photographer_name}`}
        label="Reason (sent to both people, stored in the audit log)"
        placeholder="e.g. Photographer is unreachable and the event is tomorrow."
        confirmLabel="Cancel booking"
        danger
        loading={forceCancel.isPending}
        onCancel={() => setCancelling(false)}
        onConfirm={(reason) =>
          forceCancel.mutate(
            { id: booking.id, reason },
            {
              onSuccess: () => {
                setCancelling(false);
                Alert.alert('Booking cancelled', 'Both people have been notified.');
              },
              onError: (error) =>
                Alert.alert('Could not cancel', (error as ApiError)?.message ?? 'Please try again.'),
            },
          )
        }
      />
    </SafeAreaView>
  );
}

function PersonRow({
  role,
  name,
  email,
  onPress,
}: {
  role: string;
  name: string;
  email: string;
  onPress: () => void;
}) {
  return (
    <View style={styles.person}>
      <View style={styles.personBody}>
        <Text style={styles.sub}>{role}</Text>
        <Text style={styles.personName}>{name}</Text>
        <Text style={styles.sub}>{email}</Text>
      </View>
      <Button label="View user" variant="ghost" size="sm" fullWidth={false} onPress={onPress} />
    </View>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.sm },
  service: { ...typography.h3, color: colors.text, flex: 1 },
  sub: { ...typography.caption, color: colors.sub },
  body: { ...typography.body, color: colors.text },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.sm },
  person: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  personBody: { flex: 1 },
  personName: { ...typography.bodyBold, color: colors.text },
  step: { flexDirection: 'row', gap: spacing.md, paddingVertical: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.gold, marginTop: 6 },
  stepBody: { flex: 1 },
  stepTitle: { ...typography.caption, color: colors.text, fontWeight: '600' },
  stepMeta: { ...typography.tiny, color: colors.sub },
  stepNote: { ...typography.caption, color: colors.text },
  actions: { marginTop: spacing.xl, gap: spacing.sm },
  note: { ...typography.caption, color: colors.sub, textAlign: 'center' },
});
