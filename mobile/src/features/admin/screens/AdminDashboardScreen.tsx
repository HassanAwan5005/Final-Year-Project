import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { colors, radius, spacing, typography } from '../../../theme';
import { formatCount, formatPKRShort } from '../../../utils/format';
import { AdminHeader, adminStyles, Card, SectionTitle } from '../components/AdminUI';
import { useAdminDashboard } from '../hooks/useAdmin';

/**
 * Admin home: "is anything waiting for me?" (open reports) and "is the
 * platform healthy?" (live totals + the last 30 days from the nightly rollup).
 */
export function AdminDashboardScreen({
  onOpenReports,
  onOpenUsers,
  onOpenBookings,
}: {
  onOpenReports: () => void;
  onOpenUsers: () => void;
  onOpenBookings: () => void;
}) {
  const dashboard = useAdminDashboard();

  if (dashboard.isLoading) {
    return (
      <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
        <LoadingState label="Loading dashboard…" />
      </SafeAreaView>
    );
  }
  if (dashboard.isError || !dashboard.data) {
    return (
      <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
        <ErrorState
          message={(dashboard.error as ApiError)?.message}
          onRetry={() => dashboard.refetch()}
        />
      </SafeAreaView>
    );
  }

  const { queues, totals, trend, window_days } = dashboard.data;
  const sum = (pick: (row: (typeof trend)[number]) => number) =>
    trend.reduce((total, row) => total + pick(row), 0);
  const recent = {
    newUsers: sum((row) => row.new_users),
    bookings: sum((row) => row.bookings_created),
    completed: sum((row) => row.bookings_completed),
    reviews: sum((row) => row.reviews_posted),
    value: sum((row) => Number(row.gross_booking_value) || 0),
  };

  // Last 14 days of new bookings, drawn as plain bars (no chart library).
  const bars = trend.slice(-14);
  const maxBar = Math.max(1, ...bars.map((row) => row.bookings_created));

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader title="Dashboard" subtitle="Admin · platform overview" />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={dashboard.isRefetching}
            onRefresh={() => {
              dashboard.refetch();
            }}
            tintColor={colors.gold}
          />
        }
      >
        {/* ─── Needs attention ─────────────────────────────────────────── */}
        <Pressable onPress={onOpenReports} accessibilityRole="button">
          <Card style={[styles.alert, queues.open_flags > 0 && styles.alertActive]}>
            <View style={styles.alertRow}>
              <Ionicons
                name={queues.open_flags > 0 ? 'flag' : 'checkmark-circle-outline'}
                size={22}
                color={queues.open_flags > 0 ? colors.amber : colors.green}
              />
              <View style={styles.flex}>
                <Text style={styles.alertTitle}>
                  {queues.open_flags > 0
                    ? `${queues.open_flags} open report${queues.open_flags === 1 ? '' : 's'}`
                    : 'No open reports'}
                </Text>
                <Text style={styles.alertDetail}>
                  Reported ads, reviews and chat messages
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.sub} />
            </View>
          </Card>
        </Pressable>

        {/* ─── People ──────────────────────────────────────────────────── */}
        <SectionTitle>Users</SectionTitle>
        <Pressable onPress={onOpenUsers} accessibilityRole="button">
          <View style={styles.grid}>
            <Stat label="Total users" value={formatCount(totals.users)} />
            <Stat label="Buyers" value={formatCount(totals.buyers)} />
            <Stat label="Photographers" value={formatCount(totals.photographers)} />
            <Stat
              label="Blocked"
              value={formatCount(totals.blocked_users)}
              tone={totals.blocked_users > 0 ? colors.red : undefined}
            />
          </View>
        </Pressable>

        {/* ─── Bookings ────────────────────────────────────────────────── */}
        <SectionTitle>Bookings</SectionTitle>
        <Pressable onPress={onOpenBookings} accessibilityRole="button">
          <View style={styles.grid}>
            <Stat label="All time" value={formatCount(totals.bookings_total)} />
            <Stat label="Pending" value={formatCount(totals.bookings_pending)} tone={colors.amber} />
            <Stat label="Upcoming" value={formatCount(totals.bookings_accepted)} tone={colors.green} />
            <Stat label="Completed" value={formatCount(totals.bookings_completed)} tone={colors.blue} />
          </View>
        </Pressable>
        <Card style={styles.gmv}>
          <Text style={styles.gmvLabel}>Completed booking value (all time)</Text>
          <Text style={styles.gmvValue}>{formatPKRShort(totals.booking_gmv)}</Text>
        </Card>

        {/* ─── Last 30 days ────────────────────────────────────────────── */}
        <SectionTitle>{`Last ${window_days} days`}</SectionTitle>
        <View style={styles.grid}>
          <Stat label="New users" value={formatCount(recent.newUsers)} />
          <Stat label="New bookings" value={formatCount(recent.bookings)} />
          <Stat label="Completed" value={formatCount(recent.completed)} />
          <Stat label="Reviews" value={formatCount(recent.reviews)} />
        </View>

        <Card style={styles.chartCard}>
          <Text style={styles.chartTitle}>New bookings · last 14 days</Text>
          <View style={styles.chart}>
            {bars.map((row) => (
              <View key={row.date} style={styles.barSlot}>
                <View
                  style={[
                    styles.bar,
                    { height: Math.max(2, (row.bookings_created / maxBar) * 90) },
                  ]}
                />
              </View>
            ))}
          </View>
          <Text style={styles.chartNote}>
            {recent.bookings === 0
              ? 'No activity recorded yet — the nightly analytics job fills this chart.'
              : `Booking value in the period: ${formatPKRShort(recent.value)}`}
          </Text>
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, tone ? { color: tone } : null]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge },
  alert: { marginTop: spacing.xs },
  alertActive: { borderColor: colors.amber },
  alertRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  alertTitle: { ...typography.bodyBold, color: colors.text },
  alertDetail: { ...typography.caption, color: colors.sub },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  stat: {
    flexGrow: 1,
    flexBasis: '46%',
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  statValue: { ...typography.h2, color: colors.text },
  statLabel: { ...typography.caption, color: colors.sub },
  gmv: { marginTop: spacing.sm },
  gmvLabel: { ...typography.caption, color: colors.sub },
  gmvValue: { ...typography.h2, color: colors.gold },
  chartCard: { marginTop: spacing.sm },
  chartTitle: { ...typography.caption, color: colors.sub, marginBottom: spacing.sm },
  chart: { flexDirection: 'row', alignItems: 'flex-end', height: 96, gap: 4 },
  barSlot: { flex: 1, justifyContent: 'flex-end' },
  bar: { backgroundColor: colors.gold, borderRadius: 3 },
  chartNote: { ...typography.tiny, color: colors.sub, marginTop: spacing.sm },
});
