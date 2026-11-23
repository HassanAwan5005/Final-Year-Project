import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { colors, radius, spacing, typography } from '../../../theme';
import { formatCount, formatPKR } from '../../../utils/format';
import type { SellerProduct } from '../../../types/models';
import { ProductThumb } from '../components/ProductThumb';
import {
  useDeleteListing,
  useSellerProducts,
  useSellerSummary,
  useSetListingSold,
} from '../hooks/useShop';

/**
 * What a seller (buyer or photographer) has listed. Each ad can be edited.
 *
 * New listings are created from the Shop tab's Sell form and are "Live" at
 * once — there is no admin approval. An ad an admin took down shows "Removed".
 */
export function SellerProductsScreen({
  onBack,
  onOpenProduct,
  onEditProduct,
}: {
  onBack: () => void;
  onOpenProduct: (slug: string) => void;
  onEditProduct: (productId: number) => void;
}) {
  const products = useSellerProducts();
  const summary = useSellerSummary();
  const setSold = useSetListingSold();
  const deleteListing = useDeleteListing();

  const failed = (title: string) => (error: unknown) =>
    Alert.alert(title, (error as ApiError)?.message ?? 'Please try again.');

  /** Mark sold / back on sale, and delete — the seller's other ad actions. */
  const adOptions = (product: SellerProduct) =>
    Alert.alert(product.title, undefined, [
      product.is_sold
        ? {
            text: 'Mark as available',
            onPress: () =>
              setSold.mutate(
                { id: product.id, sold: false },
                { onError: failed('Could not put the ad back on sale') },
              ),
          }
        : {
            text: 'Mark as sold',
            onPress: () =>
              setSold.mutate(
                { id: product.id, sold: true },
                { onError: failed('Could not mark the ad as sold') },
              ),
          },
      {
        text: 'Delete ad',
        style: 'destructive',
        onPress: () =>
          Alert.alert(
            'Delete this ad?',
            'It will be removed from the shop and from your listings. This cannot be undone.',
            [
              { text: 'Cancel', style: 'cancel' },
              {
                text: 'Delete',
                style: 'destructive',
                onPress: () =>
                  deleteListing.mutate(product.id, {
                    onError: failed('Could not delete the ad'),
                  }),
              },
            ],
          ),
      },
      { text: 'Cancel', style: 'cancel' },
    ]);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
        <Text style={styles.headerTitle}>My products</Text>
        <View style={styles.headerSpacer} />
      </View>

      {products.isLoading ? (
        <LoadingState label="Loading your catalogue…" />
      ) : products.isError ? (
        <ErrorState
          message={(products.error as ApiError)?.message}
          onRetry={() => products.refetch()}
        />
      ) : (
        <FlatList
          data={products.data ?? []}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={products.data?.length ? styles.list : styles.listEmpty}
          ListHeaderComponent={
            summary.data ? (
              <View style={styles.summary}>
                <View style={styles.summaryRow}>
                  <Metric
                    value={String(summary.data.products_total)}
                    label="Listings"
                  />
                  <Metric
                    value={String(summary.data.products_live)}
                    label="Live listings"
                    highlight
                  />
                </View>
                <Text style={styles.summaryNote}>
                  Interested buyers message you from your ad.
                </Text>
              </View>
            ) : undefined
          }
          renderItem={({ item }) => (
            <SellerRow
              product={item}
              onPress={() => onOpenProduct(item.slug)}
              onEdit={() => onEditProduct(item.id)}
              onMore={() => adOptions(item)}
            />
          )}
          ListEmptyComponent={
            <EmptyState
              icon="pricetags-outline"
              title="No products yet"
              detail="Products you list in the SnapSphere shop appear here."
            />
          }
          refreshControl={
            <RefreshControl
              refreshing={products.isRefetching}
              onRefresh={() => {
                products.refetch();
                summary.refetch();
              }}
              tintColor={colors.gold}
            />
          }
        />
      )}
    </SafeAreaView>
  );
}

function SellerRow({
  product,
  onPress,
  onEdit,
  onMore,
}: {
  product: SellerProduct;
  onPress: () => void;
  onEdit: () => void;
  onMore: () => void;
}) {
  // New ads are live at once. `is_approved` is now only cleared when an admin
  // takes an ad down, so a published-but-unapproved ad is a removed one.
  const live = product.is_published && product.is_approved && !product.is_sold;
  const label = product.is_sold
    ? 'Sold'
    : live
      ? 'Live'
      : product.is_published
        ? 'Removed'
        : 'Draft';

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
      accessibilityRole="button"
    >
      <ProductThumb
        uri={product.thumbnail_url}
        title={product.title}
        productType={product.product_type}
        style={styles.thumb}
        iconSize={18}
      />

      <View style={styles.rowBody}>
        <Text style={styles.rowTitle} numberOfLines={2}>
          {product.title}
        </Text>
        <Text style={styles.rowMeta}>
          {product.type_label} · {formatCount(product.view_count)} views
        </Text>
      </View>

      <View style={styles.rowRight}>
        <Text style={styles.rowPrice}>{formatPKR(product.price)}</Text>
        <Text
          style={[
            styles.rowStatus,
            product.is_sold ? styles.statusSold : live ? styles.statusLive : styles.statusDraft,
          ]}
        >
          {label}
        </Text>
        <View style={styles.actions}>
          <Pressable
            onPress={onEdit}
            hitSlop={10}
            style={styles.edit}
            accessibilityRole="button"
            accessibilityLabel={`Edit ${product.title}`}
          >
            <Ionicons name="create-outline" size={13} color={colors.gold} />
            <Text style={styles.editText}>Edit</Text>
          </Pressable>
          <Pressable
            onPress={onMore}
            hitSlop={10}
            style={styles.edit}
            accessibilityRole="button"
            accessibilityLabel={`More options for ${product.title}: mark as sold or delete`}
          >
            <Ionicons name="ellipsis-horizontal" size={15} color={colors.gold} />
          </Pressable>
        </View>
      </View>
    </Pressable>
  );
}

function Metric({
  value,
  label,
  highlight,
}: {
  value: string;
  label: string;
  highlight?: boolean;
}) {
  return (
    <View style={styles.metric}>
      <Text style={[styles.metricValue, highlight && styles.metricHighlight]} numberOfLines={1}>
        {value}
      </Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
  },
  headerTitle: { ...typography.h3, color: colors.text },
  headerSpacer: { width: 24 },
  list: { padding: spacing.xl, paddingTop: 0 },
  listEmpty: { flexGrow: 1 },
  summary: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  summaryRow: { flexDirection: 'row', marginBottom: spacing.md },
  metric: { flex: 1 },
  metricValue: { ...typography.h3, color: colors.text },
  metricHighlight: { color: colors.gold },
  metricLabel: { ...typography.tiny, color: colors.sub, marginTop: 2 },
  summaryNote: { ...typography.tiny, color: colors.dim, marginTop: spacing.xs },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  rowPressed: { backgroundColor: colors.cardHover },
  thumb: { width: 56, height: 44, borderRadius: radius.sm },
  rowBody: { flex: 1 },
  rowTitle: { ...typography.caption, color: colors.text, fontWeight: '600' },
  rowMeta: { ...typography.tiny, color: colors.sub, marginTop: 2 },
  rowRight: { alignItems: 'flex-end' },
  rowPrice: { ...typography.caption, color: colors.gold, fontWeight: '700' },
  rowStatus: { ...typography.tiny, marginTop: 2 },
  edit: { flexDirection: 'row', alignItems: 'center', gap: 3, marginTop: spacing.xs },
  editText: { ...typography.tiny, color: colors.gold, fontWeight: '600' },
  statusLive: { color: colors.green },
  statusDraft: { color: colors.dim },
  statusSold: { color: colors.amber },
  actions: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
});
