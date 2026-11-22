import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { colors, spacing } from '../../../theme';
import { useSellerProduct } from '../hooks/useShop';
import { SellProductScreen } from './SellProductScreen';

/** The Sell form, filled in with one of the seller's own ads. */
export function EditProductScreen({
  productId,
  onBack,
  onSaved,
}: {
  productId: number;
  onBack: () => void;
  onSaved: () => void;
}) {
  const listing = useSellerProduct(productId);

  // The form copies the ad once, so it must not start from a cached older one.
  if (listing.data && listing.isFetchedAfterMount) {
    return (
      <SellProductScreen listing={listing.data} onBack={onBack} onSubmitted={onSaved} />
    );
  }
  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <Pressable
        onPress={onBack}
        hitSlop={12}
        style={styles.back}
        accessibilityLabel="Go back"
      >
        <Ionicons name="chevron-back" size={24} color={colors.text} />
      </Pressable>
      {listing.isError ? (
        <ErrorState
          message={(listing.error as ApiError)?.message}
          onRetry={() => listing.refetch()}
        />
      ) : (
        <LoadingState label="Loading your ad…" />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  back: { paddingHorizontal: spacing.lg, paddingTop: spacing.md },
});
