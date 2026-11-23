import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { Image } from 'expo-image';
import React, { useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { Button } from '../../../components/ui/Button';
import { colors, radius, spacing, typography } from '../../../theme';
import type { SellerProductDetail } from '../../../types/models';
import { useCreateListing, useUpdateListing } from '../hooks/useShop';

const MAX_PHOTOS = 5;
const MIN_ADDRESS = 5;

/** A photo already on the ad (`path`) or one just picked (`asset`). */
interface FormPhoto {
  uri: string;
  path?: string;
  asset?: ImagePicker.ImagePickerAsset;
}

/** Mirrors the backend's ProductType choices. */
const PRODUCT_TYPES = [
  { value: 'CAMERA_ACCESSORY', label: 'Camera Accessories' },
  { value: 'MOBILE_ACCESSORY', label: 'Mobile Accessories' },
  { value: 'LENS', label: 'Camera Lenses' },
  { value: 'LIGHTING_AUDIO', label: 'Lighting & Mics' },
  { value: 'TRIPOD_GIMBAL', label: 'Gimbals & Tripods' },
  { value: 'OTHER', label: 'Other Gear' },
];

/**
 * The Sell form — open to buyers and photographers.
 *
 * Asks for the product photos and a description (plus a title, category, price
 * and address, which every listing in the shop needs). The listing is live in
 * the shop as soon as it is posted — there is no admin approval step.
 *
 * With a `listing` it edits that ad instead, photos included.
 */
export function SellProductScreen({
  listing,
  onBack,
  onSubmitted,
}: {
  listing?: SellerProductDetail;
  onBack: () => void;
  onSubmitted: () => void;
}) {
  const [photos, setPhotos] = useState<FormPhoto[]>(
    () => listing?.photos.map(({ path, url }) => ({ uri: url, path })) ?? [],
  );
  const [title, setTitle] = useState(listing?.title ?? '');
  const [description, setDescription] = useState(listing?.description ?? '');
  const [price, setPrice] = useState(listing ? String(Number(listing.price)) : '');
  const [productType, setProductType] = useState<string | null>(
    listing?.product_type ?? null,
  );
  const [address, setAddress] = useState(listing?.address ?? '');

  const createListing = useCreateListing();
  const updateListing = useUpdateListing();
  const isPending = createListing.isPending || updateListing.isPending;

  const priceValue = Number(price);
  const problems = [
    !photos.length && 'add at least one photo',
    title.trim().length < 3 && 'add a title',
    description.trim().length < 10 && 'write a description (10+ characters)',
    !productType && 'choose a category',
    !(priceValue >= 1) && 'enter a price',
    address.trim().length < MIN_ADDRESS && 'enter the address',
  ].filter(Boolean) as string[];
  const canSubmit = problems.length === 0 && !isPending;

  const pickPhotos = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Photo access needed', 'Allow photo access to add pictures of your product.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsMultipleSelection: true,
      selectionLimit: MAX_PHOTOS - photos.length,
      quality: 0.9,
    });
    if (!result.canceled) {
      const picked = result.assets.map((asset) => ({ uri: asset.uri, asset }));
      setPhotos((current) => {
        const known = new Set(current.map((photo) => photo.uri));
        return [...current, ...picked.filter((photo) => !known.has(photo.uri))].slice(
          0,
          MAX_PHOTOS,
        );
      });
    }
  };

  const submit = () => {
    if (!canSubmit || !productType) return;
    const payload = {
      title: title.trim(),
      description: description.trim(),
      price: priceValue,
      product_type: productType,
      address: address.trim(),
      photos: photos.flatMap(({ asset }) =>
        asset
          ? [
              {
                uri: asset.uri,
                name: asset.fileName ?? undefined,
                type: asset.mimeType ?? 'image/jpeg',
              },
            ]
          : [],
      ),
    };
    const done = (heading: string, detail: string) =>
      Alert.alert(heading, detail, [{ text: 'OK', onPress: onSubmitted }], {
        cancelable: true,
        onDismiss: onSubmitted,
      });
    const onError = (error: unknown) =>
      Alert.alert(
        listing ? 'Could not update your ad' : 'Could not list your product',
        (error as ApiError)?.message ?? 'Please try again.',
      );

    if (listing) {
      updateListing.mutate(
        {
          ...payload,
          id: listing.id,
          keep_photos: photos.flatMap(({ path }) => (path ? [path] : [])),
        },
        {
          onSuccess: (updated) =>
            updated.is_published && updated.is_approved
              ? done('Ad updated', 'Your changes are live in the shop.')
              : done(
                  'Changes saved',
                  'Your changes are saved, but this ad was removed by our team and is not in the shop.',
                ),
          onError,
        },
      );
      return;
    }
    createListing.mutate(payload, {
      onSuccess: () =>
        done(
          'Ad posted',
          'Your ad is live in the shop. You can manage it under My listings.',
        ),
      onError,
    });
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
        <Text style={styles.headerTitle}>{listing ? 'Edit ad' : 'Sell a product'}</Text>
        <View style={styles.headerSpacer} />
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.body}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* ─── Photos ──────────────────────────────────────────────────── */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Product photos</Text>
            <Text style={styles.hint}>
              Up to {MAX_PHOTOS}. The first photo is the cover.
            </Text>
            <View style={styles.photoRow}>
              {photos.map((photo, index) => (
                <View key={photo.uri} style={styles.photoWrap}>
                  <Image source={{ uri: photo.uri }} style={styles.photo} contentFit="cover" />
                  {index === 0 ? (
                    <View style={styles.coverTag}>
                      <Text style={styles.coverTagText}>Cover</Text>
                    </View>
                  ) : null}
                  <Pressable
                    style={styles.photoRemove}
                    hitSlop={6}
                    accessibilityLabel={`Remove photo ${index + 1}`}
                    onPress={() =>
                      setPhotos((current) => current.filter((p) => p.uri !== photo.uri))
                    }
                  >
                    <Ionicons name="close" size={13} color={colors.text} />
                  </Pressable>
                </View>
              ))}
              {photos.length < MAX_PHOTOS ? (
                <Pressable
                  style={styles.photoAdd}
                  onPress={pickPhotos}
                  accessibilityLabel="Add photos"
                >
                  <Ionicons name="camera-outline" size={22} color={colors.sub} />
                  <Text style={styles.photoAddText}>Add</Text>
                </Pressable>
              ) : null}
            </View>
          </View>

          {/* ─── Details ─────────────────────────────────────────────────── */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Title</Text>
            <TextInput
              value={title}
              onChangeText={setTitle}
              placeholder="e.g. Canon 50mm f/1.8 lens"
              placeholderTextColor={colors.dim}
              maxLength={160}
              style={styles.input}
            />

            <Text style={[styles.cardTitle, styles.spaced]}>Description</Text>
            <TextInput
              value={description}
              onChangeText={setDescription}
              placeholder="Condition, what's included, why you're selling…"
              placeholderTextColor={colors.dim}
              multiline
              maxLength={5000}
              style={[styles.input, styles.textarea]}
            />
            <Text style={styles.counter}>{description.length}/5000</Text>

            <Text style={[styles.cardTitle, styles.spaced]}>Category</Text>
            <View style={styles.chips}>
              {PRODUCT_TYPES.map((type) => {
                const active = productType === type.value;
                return (
                  <Pressable
                    key={type.value}
                    onPress={() => setProductType(type.value)}
                    style={[styles.chip, active && styles.chipActive]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: active }}
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>
                      {type.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={[styles.cardTitle, styles.spaced]}>Price (Rs)</Text>
            <TextInput
              value={price}
              onChangeText={(text) => setPrice(text.replace(/[^0-9]/g, ''))}
              placeholder="e.g. 18000"
              placeholderTextColor={colors.dim}
              keyboardType="number-pad"
              maxLength={8}
              style={styles.input}
            />

            <Text style={[styles.cardTitle, styles.spaced]}>Address</Text>
            <TextInput
              value={address}
              onChangeText={setAddress}
              placeholder="e.g. Gulberg III, Lahore"
              placeholderTextColor={colors.dim}
              maxLength={300}
              style={styles.input}
            />
            <Text style={styles.addressHint}>Everyone who opens your ad can see this.</Text>
          </View>

          <Text style={styles.footnote}>
            {listing
              ? 'Your changes go live in the shop as soon as you save.'
              : 'Your ad goes live in the shop as soon as you post it.'}
          </Text>
        </ScrollView>

        <View style={styles.bar}>
          {problems.length && !isPending ? (
            <Text style={styles.missing} numberOfLines={2}>
              {listing ? 'To save' : 'To post'}: {problems.join(', ')}.
            </Text>
          ) : null}
          <Button
            label={listing ? 'Save changes' : 'Post ad'}
            onPress={submit}
            disabled={!canSubmit}
            loading={isPending}
          />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: { ...typography.h3, color: colors.text },
  headerSpacer: { width: 24 },
  body: { padding: spacing.xl, gap: spacing.lg, paddingBottom: spacing.huge },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  cardTitle: { ...typography.bodyBold, color: colors.text, marginBottom: spacing.sm },
  spaced: { marginTop: spacing.lg },
  hint: { ...typography.tiny, color: colors.sub, marginBottom: spacing.md },
  input: {
    ...typography.body,
    color: colors.text,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  textarea: { minHeight: 110, textAlignVertical: 'top' },
  addressHint: { ...typography.tiny, color: colors.dim, marginTop: 4 },
  counter: { ...typography.tiny, color: colors.dim, textAlign: 'right', marginTop: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.goldDim, borderColor: colors.gold },
  chipText: { ...typography.caption, color: colors.sub },
  chipTextActive: { color: colors.goldLight },
  photoRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  photoWrap: { position: 'relative' },
  photo: { width: 76, height: 76, borderRadius: radius.md },
  coverTag: {
    position: 'absolute',
    left: 4,
    bottom: 4,
    backgroundColor: colors.bg,
    borderRadius: radius.sm,
    paddingHorizontal: 4,
  },
  coverTagText: { ...typography.tiny, color: colors.gold, fontSize: 10 },
  photoRemove: {
    position: 'absolute',
    top: -6,
    right: -6,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  photoAdd: {
    width: 76,
    height: 76,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  photoAddText: { ...typography.tiny, color: colors.sub, marginTop: 2 },
  footnote: { ...typography.tiny, color: colors.dim, textAlign: 'center' },
  bar: {
    padding: spacing.lg,
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  missing: { ...typography.tiny, color: colors.sub, textAlign: 'center' },
});
