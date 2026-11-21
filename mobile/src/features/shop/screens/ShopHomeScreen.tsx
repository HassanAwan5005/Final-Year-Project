import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, radius, spacing, typography } from '../../../theme';

/**
 * The Shop tab's landing page — the same for buyers and photographers.
 *
 * Two choices: Buy opens the existing product grid; Sell opens the listing
 * form (photos, details, price).
 */
export function ShopHomeScreen({
  onBuy,
  onSell,
  onOpenMyListings,
}: {
  onBuy: () => void;
  onSell: () => void;
  onOpenMyListings: () => void;
}) {
  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Text style={styles.title}>Shop</Text>
        <Text style={styles.subtitle}>What would you like to do?</Text>
      </View>

      <View style={styles.body}>
        <Choice
          icon="bag-handle"
          title="Buy"
          detail="Browse camera gear, mobile accessories and more."
          onPress={onBuy}
        />
        <Choice
          icon="pricetag"
          title="Sell"
          detail="Add photos and a description to list your product for sale."
          onPress={onSell}
        />

        <Pressable
          onPress={onOpenMyListings}
          style={styles.myListings}
          accessibilityRole="button"
        >
          <Ionicons name="list-outline" size={16} color={colors.gold} />
          <Text style={styles.myListingsText}>My listings</Text>
          <Ionicons name="chevron-forward" size={15} color={colors.gold} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function Choice({
  icon,
  title,
  detail,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  detail: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.choice, pressed && styles.choicePressed]}
      accessibilityRole="button"
      accessibilityLabel={title}
    >
      <View style={styles.choiceIcon}>
        <Ionicons name={icon} size={28} color={colors.gold} />
      </View>
      <View style={styles.choiceBody}>
        <Text style={styles.choiceTitle}>{title}</Text>
        <Text style={styles.choiceDetail}>{detail}</Text>
      </View>
      <Ionicons name="chevron-forward" size={20} color={colors.sub} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  header: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  title: { ...typography.h1, color: colors.text },
  subtitle: { ...typography.caption, color: colors.sub },
  body: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  choice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.lg,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.xl,
  },
  choicePressed: { opacity: 0.85 },
  choiceIcon: {
    width: 56,
    height: 56,
    borderRadius: radius.lg,
    backgroundColor: colors.goldDim,
    alignItems: 'center',
    justifyContent: 'center',
  },
  choiceBody: { flex: 1 },
  choiceTitle: { ...typography.h2, color: colors.text },
  choiceDetail: { ...typography.caption, color: colors.sub, marginTop: 2 },
  myListings: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.md,
  },
  myListingsText: { ...typography.caption, color: colors.gold },
});
