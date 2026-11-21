import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Modal,
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
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { Button } from '../../../components/ui/Button';
import { colors, radius, spacing, typography } from '../../../theme';
import { formatPKR } from '../../../utils/format';
import type { CartLine } from '../../../types/models';
import { ProductThumb } from '../components/ProductThumb';
import {
  useCart,
  useCheckout,
  useClearCart,
  useRemoveFromCart,
} from '../hooks/useShop';

/** An 11-digit Pakistani mobile number, e.g. 03001234567. */
const PHONE_RE = /^03\d{9}$/;
const MIN_ADDRESS = 10;

/**
 * The basket and cash-on-delivery checkout.
 *
 * There are no online payments. Adding to the cart needs nothing; only when
 * the buyer confirms the order are they asked for a delivery address and an
 * 11-digit phone number (both required). They pay in cash on delivery.
 */
export function CartScreen({
  onBack,
  onOpenProduct,
  onPurchased,
}: {
  onBack: () => void;
  onOpenProduct: (slug: string) => void;
  onPurchased: (orderId: number) => void;
}) {
  const cart = useCart();
  const removeItem = useRemoveFromCart();
  const clearCart = useClearCart();
  const checkout = useCheckout();

  // The confirm-order sheet and its fields. Nothing is pre-filled.
  const [confirming, setConfirming] = useState(false);
  const [address, setAddress] = useState('');
  const [phone, setPhone] = useState('');
  const [triedSubmit, setTriedSubmit] = useState(false);

  if (cart.isLoading) return <LoadingState label="Loading your cart…" />;
  if (cart.isError || !cart.data) {
    return (
      <ErrorState
        message={(cart.error as ApiError)?.message}
        onRetry={() => cart.refetch()}
      />
    );
  }

  const { items, total, can_checkout, unavailable_count } = cart.data;

  const addressOk = address.trim().length >= MIN_ADDRESS;
  const phoneOk = PHONE_RE.test(phone);
  const showAddressError = (triedSubmit || address.length > 0) && !addressOk;
  const showPhoneError = (triedSubmit || phone.length > 0) && !phoneOk;

  const openConfirm = () => {
    setTriedSubmit(false);
    setConfirming(true);
  };

  const confirmOrder = () => {
    setTriedSubmit(true);
    if (!addressOk || !phoneOk) return;
    checkout.mutate(
      { delivery_address: address.trim(), delivery_phone: phone },
      {
        onSuccess: (order) => {
          setConfirming(false);
          Alert.alert(
            'Order placed',
            `Pay ${formatPKR(order.total)} in cash when your order is delivered.`,
            [{ text: 'OK', onPress: () => onPurchased(order.id) }],
            { cancelable: true, onDismiss: () => onPurchased(order.id) },
          );
        },
        onError: (error) => {
          Alert.alert('Could not place the order', (error as ApiError).message);
          cart.refetch();
        },
      },
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Cart</Text>
        {items.length ? (
          <Pressable
            onPress={() =>
              Alert.alert('Empty the cart?', 'This removes everything in it.', [
                { text: 'Keep', style: 'cancel' },
                { text: 'Empty', style: 'destructive', onPress: () => clearCart.mutate(undefined) },
              ])
            }
            hitSlop={12}
          >
            <Text style={styles.clear}>Clear</Text>
          </Pressable>
        ) : (
          <View style={styles.headerSpacer} />
        )}
      </View>

      {items.length === 0 ? (
        <EmptyState
          icon="cart-outline"
          title="Your cart is empty"
          detail="Products you add will show up here."
        />
      ) : (
        <>
          <ScrollView contentContainerStyle={styles.list}>
            {unavailable_count > 0 ? (
              <View style={styles.warning}>
                <Ionicons name="alert-circle-outline" size={16} color={colors.amber} />
                <Text style={styles.warningText}>
                  {unavailable_count === 1
                    ? 'One item can no longer be bought. Remove it to check out.'
                    : `${unavailable_count} items can no longer be bought. Remove them to check out.`}
                </Text>
              </View>
            ) : null}

            {items.map((line) => (
              <CartRow
                key={line.id}
                line={line}
                onPress={() => onOpenProduct(line.product.slug)}
                onRemove={() => removeItem.mutate(line.product.id)}
              />
            ))}
          </ScrollView>

          <View style={styles.footer}>
            <Row label="Subtotal" value={formatPKR(total)} />
            <Row label="Payment" value="Cash on delivery" muted />

            <View style={styles.totalRow}>
              <Text style={styles.totalLabel}>Total</Text>
              <Text style={styles.totalValue}>{formatPKR(total)}</Text>
            </View>

            <Button label="Checkout" onPress={openConfirm} disabled={!can_checkout} />

            <Text style={styles.note}>Pay in cash when your order is delivered.</Text>
          </View>
        </>
      )}

      {/* ─── Confirm order: delivery details are required here only ─────── */}
      <Modal
        visible={confirming}
        transparent
        animationType="slide"
        onRequestClose={() => setConfirming(false)}
      >
        <KeyboardAvoidingView
          style={styles.sheetBackdrop}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          <View style={styles.sheet}>
            <View style={styles.sheetHeader}>
              <Text style={styles.sheetTitle}>Confirm order</Text>
              <Pressable
                onPress={() => setConfirming(false)}
                hitSlop={10}
                accessibilityLabel="Close"
              >
                <Ionicons name="close" size={22} color={colors.sub} />
              </Pressable>
            </View>

            <ScrollView keyboardShouldPersistTaps="handled">
              <Text style={styles.fieldLabel}>Delivery address *</Text>
              <TextInput
                value={address}
                onChangeText={setAddress}
                placeholder="House, street, area, city"
                placeholderTextColor={colors.dim}
                multiline
                maxLength={500}
                style={[styles.input, styles.addressInput]}
              />
              {showAddressError ? (
                <Text style={styles.fieldError}>
                  {address.trim() ? 'Enter your full address.' : 'Delivery address is required.'}
                </Text>
              ) : null}

              <Text style={styles.fieldLabel}>Phone number *</Text>
              <TextInput
                value={phone}
                onChangeText={(text) => setPhone(text.replace(/[^0-9]/g, ''))}
                placeholder="03XXXXXXXXX"
                placeholderTextColor={colors.dim}
                keyboardType="number-pad"
                maxLength={11}
                style={styles.input}
              />
              {showPhoneError ? (
                <Text style={styles.fieldError}>
                  {phone
                    ? 'Enter an 11-digit Pakistani mobile number, e.g. 03001234567.'
                    : 'Phone number is required.'}
                </Text>
              ) : null}

              <View style={styles.sheetTotal}>
                <Text style={styles.summaryLabel}>Total (cash on delivery)</Text>
                <Text style={styles.totalValue}>{formatPKR(total)}</Text>
              </View>
            </ScrollView>

            <Button
              label="Confirm order"
              onPress={confirmOrder}
              loading={checkout.isPending}
            />
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

function CartRow({
  line,
  onPress,
  onRemove,
}: {
  line: CartLine;
  onPress: () => void;
  onRemove: () => void;
}) {
  return (
    <View style={[styles.row, !line.is_available && styles.rowDisabled]}>
      <Pressable onPress={onPress} style={styles.rowMain} accessibilityRole="button">
        <ProductThumb
          uri={line.product.thumbnail_url}
          title={line.product.title}
          productType={line.product.product_type}
          style={styles.thumb}
          iconSize={18}
        />

        <View style={styles.rowBody}>
          <Text style={styles.rowTitle} numberOfLines={2}>
            {line.product.title}
          </Text>
          <Text style={styles.rowSeller} numberOfLines={1}>
            {line.product.seller.display_name}
          </Text>
          {!line.is_available ? (
            <Text style={styles.rowUnavailable}>
              {line.is_owned ? 'Already in your library' : 'No longer on sale'}
            </Text>
          ) : null}
        </View>

        <Text style={styles.rowPrice}>{formatPKR(line.product.price)}</Text>
      </Pressable>

      <Pressable
        onPress={onRemove}
        hitSlop={10}
        accessibilityLabel={`Remove ${line.product.title}`}
        style={styles.remove}
      >
        <Ionicons name="trash-outline" size={16} color={colors.dim} />
      </Pressable>
    </View>
  );
}

function Row({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <View style={styles.summaryRow}>
      <Text style={[styles.summaryLabel, muted && styles.muted]}>{label}</Text>
      <Text style={[styles.summaryValue, muted && styles.muted]}>
        {value}
      </Text>
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
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: { ...typography.h3, color: colors.text },
  headerSpacer: { width: 34 },
  clear: { ...typography.caption, color: colors.red, fontWeight: '600' },
  list: { padding: spacing.xl },
  warning: {
    flexDirection: 'row',
    gap: spacing.sm,
    backgroundColor: colors.amberDim,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  warningText: { ...typography.caption, color: colors.amber, flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  rowDisabled: { opacity: 0.6, borderColor: colors.amberDim },
  rowMain: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  thumb: { width: 56, height: 44, borderRadius: radius.sm },
  rowBody: { flex: 1 },
  rowTitle: { ...typography.caption, color: colors.text, fontWeight: '600' },
  rowSeller: { ...typography.tiny, color: colors.sub },
  rowUnavailable: { ...typography.tiny, color: colors.amber, marginTop: 2 },
  rowPrice: { ...typography.bodyBold, color: colors.gold },
  remove: { paddingLeft: spacing.md },
  footer: {
    padding: spacing.xl,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  summaryLabel: { ...typography.caption, color: colors.text },
  summaryValue: { ...typography.caption, color: colors.text },
  muted: { color: colors.sub },
  sheetBackdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  sheet: {
    maxHeight: '85%',
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.xl,
    gap: spacing.md,
  },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sheetTitle: { ...typography.h3, color: colors.text },
  sheetTotal: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.lg,
  },
  fieldLabel: {
    ...typography.caption,
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
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
  addressInput: { minHeight: 70, textAlignVertical: 'top' },
  fieldError: { ...typography.tiny, color: colors.amber, marginTop: 4 },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingTop: spacing.md,
    marginBottom: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  totalLabel: { ...typography.h3, color: colors.text },
  totalValue: { ...typography.h3, color: colors.gold },
  note: {
    ...typography.tiny,
    color: colors.dim,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
});
