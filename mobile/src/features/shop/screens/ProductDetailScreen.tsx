import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import React, { useState } from 'react';
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import type { DigitalProductDetail } from '../../../types/models';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { Avatar } from '../../../components/ui/Avatar';
import { Button } from '../../../components/ui/Button';
import { useAuthStore } from '../../../store/authStore';
import { colors, radius, spacing, typography } from '../../../theme';
import { formatPKR } from '../../../utils/format';
import { PhotoViewer } from '../components/PhotoViewer';
import { ProductThumb } from '../components/ProductThumb';
import {
  useDeleteListing,
  useProduct,
  useReportProduct,
  useSetListingSold,
  useToggleWishlist,
} from '../hooks/useShop';
import type { FlagReason } from '../../../types/models';

/**
 * A product page.
 *
 * Buying is a conversation: anyone interested messages the seller and the two
 * agree a deal in chat. The seller sees "Edit ad" here instead.
 */
export function ProductDetailScreen({
  slug,
  onBack,
  onMessageSeller,
  onEdit,
}: {
  slug: string;
  onBack: () => void;
  onMessageSeller: (product: DigitalProductDetail) => void;
  onEdit: (productId: number) => void;
}) {
  const { width } = useWindowDimensions();
  const query = useProduct(slug);
  const toggleSave = useToggleWishlist();
  const setSold = useSetListingSold();
  const deleteListing = useDeleteListing();
  const reportAd = useReportProduct();
  const userId = useAuthStore((s) => s.user?.id);
  const [viewing, setViewing] = useState<number | null>(null);

  if (query.isLoading) return <LoadingState label="Loading product…" />;
  if (query.isError || !query.data) {
    return (
      <ErrorState
        message={(query.error as ApiError)?.message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const product = query.data;

  const isMine = product.seller.id === userId;

  // Android shows at most three Alert buttons, so two reasons + Cancel.
  const sendReport = (reason: FlagReason) =>
    reportAd.mutate(
      { slug: product.slug, reason },
      {
        onSuccess: () => Alert.alert('Reported', 'Thanks — our team will review this ad.'),
        onError: (error) => Alert.alert('Could not report', (error as ApiError).message),
      },
    );
  const confirmReport = () =>
    Alert.alert('Report this ad?', 'Our team will review it. Reporting does not remove the ad by itself.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Inappropriate', onPress: () => sendReport('INAPPROPRIATE') },
      { text: 'Fake or misleading', style: 'destructive', onPress: () => sendReport('FAKE') },
    ]);

  const photos = product.preview_image_urls.length
    ? product.preview_image_urls
    : product.thumbnail_url
      ? [product.thumbnail_url]
      : [];

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
        <View style={styles.headerActions}>
          {!isMine ? (
            <Pressable
              onPress={confirmReport}
              disabled={reportAd.isPending}
              hitSlop={12}
              accessibilityLabel="Report this ad"
            >
              <Ionicons name="flag-outline" size={21} color={colors.text} />
            </Pressable>
          ) : null}
          <Pressable
            onPress={() => toggleSave.mutate({ product: product.id })}
            hitSlop={12}
            accessibilityLabel={product.is_wishlisted ? 'Remove from saved' : 'Save'}
          >
            <Ionicons
              name={product.is_wishlisted ? 'heart' : 'heart-outline'}
              size={22}
              color={product.is_wishlisted ? colors.red : colors.text}
            />
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* ─── Gallery ─────────────────────────────────────────────────── */}
        <Pressable
          style={[styles.hero, { height: width * 0.62 }]}
          onPress={() => setViewing(0)}
          disabled={!photos.length}
          accessibilityRole="imagebutton"
          accessibilityLabel="View photos"
        >
          <ProductThumb
            // Remount when the cover changes, so an old load error is forgotten.
            key={photos[0] ?? 'none'}
            uri={photos[0] ?? null}
            title={product.title}
            productType={product.product_type}
            style={styles.heroImage}
            iconSize={38}
            showLabel
          />
          {photos.length ? (
            <View style={styles.photoCount}>
              <Ionicons name="images-outline" size={13} color={colors.white} />
              <Text style={styles.photoCountText}>{photos.length}</Text>
            </View>
          ) : null}
        </Pressable>

        {photos.length > 1 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.previews}
          >
            {photos.map((uri, index) => (
              <Pressable
                key={uri}
                onPress={() => setViewing(index)}
                accessibilityRole="imagebutton"
                accessibilityLabel={`View photo ${index + 1}`}
              >
                <Image source={{ uri }} style={styles.preview} contentFit="cover" />
              </Pressable>
            ))}
          </ScrollView>
        ) : null}

        <View style={styles.main}>
          <Text style={styles.type}>{product.type_label}</Text>
          <Text style={styles.title}>{product.title}</Text>

          <View style={styles.priceRow}>
            <Text style={styles.price}>{formatPKR(product.price)}</Text>
            {product.compare_at_price &&
            Number(product.compare_at_price) > Number(product.price) ? (
              <>
                <Text style={styles.was}>{formatPKR(product.compare_at_price)}</Text>
                <View style={styles.discountPill}>
                  <Text style={styles.discountText}>
                    Save {product.discount_percent}%
                  </Text>
                </View>
              </>
            ) : null}
          </View>

          {product.address ? (
            <View style={styles.addressRow}>
              <Ionicons name="location-outline" size={16} color={colors.gold} />
              <Text style={styles.address}>{product.address}</Text>
            </View>
          ) : null}

          {/* ─── Seller ────────────────────────────────────────────────── */}
          <View style={styles.seller}>
            <Avatar
              uri={product.seller.avatar_url}
              name={product.seller.display_name}
              size={38}
            />
            <View style={styles.sellerBody}>
              <Text style={styles.sellerName}>{product.seller.display_name}</Text>
            </View>
            {product.seller.is_verified ? (
              <Ionicons name="checkmark-circle" size={18} color={colors.blue} />
            ) : null}
          </View>

          {product.description ? (
            <Section title="Description">
              <Text style={styles.body}>{product.description}</Text>
            </Section>
          ) : null}

          {product.compatible_with?.length ? (
            <Section title="Works with">
              <View style={styles.tags}>
                {product.compatible_with.map((entry) => (
                  <View key={entry} style={styles.tag}>
                    <Text style={styles.tagText}>{entry}</Text>
                  </View>
                ))}
              </View>
            </Section>
          ) : null}
        </View>
      </ScrollView>

      {/* ─── Action bar ──────────────────────────────────────────────────── */}
      <View style={styles.actionBar}>
        {isMine ? (
          <>
            {product.is_sold ? (
              <Text style={styles.soldNote}>
                Marked as sold — buyers no longer see this ad in the shop.
              </Text>
            ) : null}
            <Button label="Edit ad" onPress={() => onEdit(product.id)} />
            <View style={styles.ownerActions}>
              <Button
                label={product.is_sold ? 'Mark as available' : 'Mark as sold'}
                variant="secondary"
                loading={setSold.isPending}
                onPress={() =>
                  setSold.mutate(
                    { id: product.id, sold: !product.is_sold },
                    {
                      onError: (error) =>
                        Alert.alert('Could not update the ad', (error as ApiError).message),
                    },
                  )
                }
                style={styles.ownerAction}
              />
              <Button
                label="Delete ad"
                variant="danger"
                loading={deleteListing.isPending}
                onPress={() =>
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
                            onSuccess: onBack,
                            onError: (error) =>
                              Alert.alert('Could not delete the ad', (error as ApiError).message),
                          }),
                      },
                    ],
                  )
                }
                style={styles.ownerAction}
              />
            </View>
          </>
        ) : (
          <Button label="Message seller" onPress={() => onMessageSeller(product)} />
        )}
      </View>

      {viewing !== null ? (
        <PhotoViewer
          uris={photos}
          initialIndex={viewing}
          onClose={() => setViewing(null)}
        />
      ) : null}
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
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
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: spacing.xl },
  content: { paddingBottom: spacing.huge },
  hero: { backgroundColor: colors.surface },
  heroImage: { width: '100%', height: '100%', borderRadius: 0 },
  previews: { gap: spacing.sm, padding: spacing.lg },
  preview: { width: 90, height: 64, borderRadius: radius.sm },
  main: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg },
  type: { ...typography.tiny, color: colors.dim, textTransform: 'uppercase' },
  title: { ...typography.h1, color: colors.text, marginTop: 2 },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: spacing.md,
    marginTop: spacing.md,
  },
  price: { ...typography.h2, color: colors.gold },
  was: { ...typography.caption, color: colors.dim, textDecorationLine: 'line-through' },
  discountPill: {
    backgroundColor: colors.greenDim,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  discountText: { ...typography.tiny, color: colors.green, fontWeight: '700' },
  photoCount: {
    position: 'absolute',
    right: spacing.md,
    bottom: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.overlay,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.sm,
  },
  photoCountText: { ...typography.tiny, color: colors.white, fontWeight: '600' },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.xs,
    marginTop: spacing.md,
  },
  address: { ...typography.body, color: colors.sub, flex: 1 },
  seller: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginTop: spacing.xl,
  },
  sellerBody: { flex: 1 },
  sellerName: { ...typography.bodyBold, color: colors.text },
  section: { marginTop: spacing.xxl },
  sectionTitle: { ...typography.h3, color: colors.text, marginBottom: spacing.md },
  body: { ...typography.body, color: colors.sub, lineHeight: 22 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tag: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.pill,
  },
  tagText: { ...typography.caption, color: colors.sub },
  actionBar: {
    padding: spacing.xl,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  ownerActions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.md },
  ownerAction: { flex: 1 },
  soldNote: {
    ...typography.caption,
    color: colors.amber,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
});
