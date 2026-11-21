import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import React, { useState } from 'react';
import {
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { Button } from '../../../components/ui/Button';
import { useAuthStore } from '../../../store/authStore';
import { colors, radius, spacing, typography } from '../../../theme';
import type { AdminListing } from '../../../types/models';
import { formatDate, formatPKR } from '../../../utils/format';
import { useApproveListing, usePendingListings, useRejectListing } from '../hooks/useAdmin';

const MIN_REASON = 10;

/**
 * The admin's moderation queue: products sellers have submitted from the
 * Shop → Sell form, waiting to be approved before they appear in the shop.
 */
export function PendingListingsScreen() {
  const logout = useAuthStore((s) => s.logout);
  const listings = usePendingListings();
  const approve = useApproveListing();
  const reject = useRejectListing();

  const [rejecting, setRejecting] = useState<AdminListing | null>(null);
  const [reason, setReason] = useState('');

  const busyId =
    (approve.isPending && approve.variables) ||
    (reject.isPending && reject.variables?.id) ||
    null;

  const fail = (title: string) => (error: unknown) =>
    Alert.alert(title, (error as ApiError)?.message ?? 'Please try again.');

  const confirmApprove = (listing: AdminListing) =>
    Alert.alert('Approve this listing?', `"${listing.title}" will appear in the shop.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Approve',
        onPress: () => approve.mutate(listing.id, { onError: fail('Could not approve') }),
      },
    ]);

  const submitReject = () => {
    if (!rejecting) return;
    const id = rejecting.id;
    reject.mutate(
      { id, reason: reason.trim() },
      {
        onSuccess: () => {
          setRejecting(null);
          setReason('');
        },
        onError: fail('Could not reject'),
      },
    );
  };

  const confirmLogout = () =>
    Alert.alert('Log out?', undefined, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Log out', style: 'destructive', onPress: () => logout() },
    ]);

  const rows = listings.data?.items ?? [];

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <View style={styles.headerText}>
          <Text style={styles.title}>Pending listings</Text>
          <Text style={styles.subtitle}>
            Admin ·{' '}
            {listings.data
              ? `${listings.data.total} waiting for approval`
              : 'products waiting for approval'}
          </Text>
        </View>
        <Pressable
          onPress={confirmLogout}
          hitSlop={10}
          style={styles.logout}
          accessibilityRole="button"
          accessibilityLabel="Log out"
        >
          <Ionicons name="log-out-outline" size={18} color={colors.red} />
          <Text style={styles.logoutText}>Log out</Text>
        </Pressable>
      </View>

      {listings.isLoading ? (
        <LoadingState label="Loading pending listings…" />
      ) : listings.isError ? (
        <ErrorState
          message={(listings.error as ApiError)?.message}
          onRetry={() => listings.refetch()}
        />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={rows.length ? styles.list : styles.listEmpty}
          refreshControl={
            <RefreshControl
              refreshing={listings.isRefetching}
              onRefresh={() => {
                listings.refetch();
              }}
              tintColor={colors.gold}
            />
          }
          ListEmptyComponent={
            <EmptyState
              icon="checkmark-done-outline"
              title="All caught up"
              detail="New products submitted from the Sell screen will appear here."
            />
          }
          renderItem={({ item }) => (
            <ListingCard
              listing={item}
              busy={busyId === item.id}
              onApprove={() => confirmApprove(item)}
              onReject={() => {
                setReason('');
                setRejecting(item);
              }}
            />
          )}
        />
      )}

      {/* ─── Reject reason ──────────────────────────────────────────────── */}
      <Modal
        visible={rejecting !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setRejecting(null)}
      >
        <KeyboardAvoidingView
          style={styles.modalBackdrop}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Reject listing</Text>
            <Text style={styles.modalDetail} numberOfLines={2}>
              {rejecting?.title}
            </Text>
            <Text style={styles.modalLabel}>Reason (sent to the seller)</Text>
            <TextInput
              value={reason}
              onChangeText={setReason}
              placeholder="e.g. Photos do not show the actual product."
              placeholderTextColor={colors.dim}
              multiline
              maxLength={1000}
              style={styles.modalInput}
              autoFocus
            />
            {reason.trim().length < MIN_REASON ? (
              <Text style={styles.modalHint}>At least {MIN_REASON} characters.</Text>
            ) : null}
            <View style={styles.modalActions}>
              <View style={styles.flex}>
                <Button
                  label="Cancel"
                  variant="secondary"
                  onPress={() => setRejecting(null)}
                  disabled={reject.isPending}
                />
              </View>
              <View style={styles.flex}>
                <Button
                  label="Reject"
                  onPress={submitReject}
                  disabled={reason.trim().length < MIN_REASON}
                  loading={reject.isPending}
                />
              </View>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

function ListingCard({
  listing,
  busy,
  onApprove,
  onReject,
}: {
  listing: AdminListing;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const photos = listing.preview_image_urls.length
    ? listing.preview_image_urls
    : listing.thumbnail_url
      ? [listing.thumbnail_url]
      : [];

  return (
    <View style={styles.card}>
      {photos.length ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.photos}
        >
          {photos.map((uri) => (
            <Image key={uri} source={{ uri }} style={styles.photo} contentFit="cover" />
          ))}
        </ScrollView>
      ) : (
        <View style={[styles.photo, styles.noPhoto]}>
          <Ionicons name="image-outline" size={22} color={colors.dim} />
        </View>
      )}

      <Text style={styles.cardTitle}>{listing.title}</Text>
      <Text style={styles.meta}>
        {listing.type_label} · {formatPKR(listing.price)}
      </Text>
      <Text style={styles.meta}>
        Seller: {listing.seller_name} · {formatDate(listing.created_at)}
      </Text>

      {listing.description ? (
        <Pressable onPress={() => setExpanded((open) => !open)}>
          <Text style={styles.description} numberOfLines={expanded ? undefined : 4}>
            {listing.description}
          </Text>
          {listing.description.length > 180 ? (
            <Text style={styles.more}>{expanded ? 'Show less' : 'Show more'}</Text>
          ) : null}
        </Pressable>
      ) : null}

      <View style={styles.actions}>
        <View style={styles.flex}>
          <Button
            label="Reject"
            variant="secondary"
            onPress={onReject}
            disabled={busy}
          />
        </View>
        <View style={styles.flex}>
          <Button label="Approve" onPress={onApprove} loading={busy} disabled={busy} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  headerText: { flex: 1 },
  title: { ...typography.h1, color: colors.text },
  subtitle: { ...typography.caption, color: colors.sub },
  logout: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  logoutText: { ...typography.caption, color: colors.red },
  list: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge, gap: spacing.lg },
  listEmpty: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: spacing.xl },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  photos: { gap: spacing.sm, paddingBottom: spacing.sm },
  photo: { width: 120, height: 120, borderRadius: radius.md, backgroundColor: colors.surface },
  noPhoto: { alignItems: 'center', justifyContent: 'center', marginBottom: spacing.sm },
  cardTitle: { ...typography.bodyBold, color: colors.text },
  meta: { ...typography.tiny, color: colors.sub },
  description: { ...typography.body, color: colors.text, marginTop: spacing.xs },
  more: { ...typography.tiny, color: colors.gold, marginTop: 2 },
  actions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.md },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  modalTitle: { ...typography.h3, color: colors.text },
  modalDetail: { ...typography.caption, color: colors.sub, marginTop: 2 },
  modalLabel: {
    ...typography.bodyBold,
    color: colors.text,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  modalInput: {
    ...typography.body,
    color: colors.text,
    backgroundColor: colors.card,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    minHeight: 90,
    textAlignVertical: 'top',
  },
  modalHint: { ...typography.tiny, color: colors.sub, marginTop: 4 },
  modalActions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.lg },
});
