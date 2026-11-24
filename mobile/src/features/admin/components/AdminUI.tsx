/**
 * Small building blocks shared by the admin screens, so the five tabs look
 * and behave the same: header, filter chips, search box, reason dialog, rows.
 */

import { Ionicons } from '@expo/vector-icons';
import React, { useEffect, useState } from 'react';
import {
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

import { Button } from '../../../components/ui/Button';
import { colors, radius, spacing, typography } from '../../../theme';

// ─── Header ────────────────────────────────────────────────────────────────
export function AdminHeader({
  title,
  subtitle,
  onBack,
  right,
}: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  right?: React.ReactNode;
}) {
  return (
    <View style={styles.header}>
      {onBack ? (
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
      ) : null}
      <View style={styles.headerText}>
        <Text style={onBack ? styles.titleSmall : styles.title} numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

// ─── Filter chips ──────────────────────────────────────────────────────────
export function FilterChips<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.chips}
      style={styles.chipsScroll}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            style={[styles.chip, active && styles.chipActive]}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

// ─── Search box ────────────────────────────────────────────────────────────
export function SearchBox({
  value,
  onChangeText,
  placeholder,
}: {
  value: string;
  onChangeText: (text: string) => void;
  placeholder: string;
}) {
  return (
    <View style={styles.search}>
      <Ionicons name="search-outline" size={17} color={colors.sub} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.dim}
        style={styles.searchInput}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
      />
      {value ? (
        <Pressable onPress={() => onChangeText('')} hitSlop={10} accessibilityLabel="Clear search">
          <Ionicons name="close-circle" size={17} color={colors.sub} />
        </Pressable>
      ) : null}
    </View>
  );
}

// ─── Small pill ────────────────────────────────────────────────────────────
export function Tag({
  label,
  tone = 'neutral',
}: {
  label: string;
  tone?: 'neutral' | 'red' | 'green' | 'amber' | 'blue' | 'gold';
}) {
  const palette = {
    neutral: { fg: colors.sub, bg: colors.border },
    red: { fg: colors.red, bg: colors.redDim },
    green: { fg: colors.green, bg: colors.greenDim },
    amber: { fg: colors.amber, bg: colors.amberDim },
    blue: { fg: colors.blue, bg: colors.blueDim },
    gold: { fg: colors.gold, bg: colors.goldDim },
  }[tone];
  return (
    <View style={[styles.tag, { backgroundColor: palette.bg }]}>
      <Text style={[styles.tagText, { color: palette.fg }]}>{label}</Text>
    </View>
  );
}

// ─── Label / value row ─────────────────────────────────────────────────────
export function InfoRow({ label, value }: { label: string; value?: string | number | null }) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{String(value)}</Text>
    </View>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: object }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function SectionTitle({ children }: { children: string }) {
  return <Text style={styles.sectionTitle}>{children}</Text>;
}

// ─── Reason dialog ─────────────────────────────────────────────────────────
/**
 * Every destructive admin action needs a typed reason (the server enforces
 * the minimum length too). The reason is shown to the affected user and
 * stored in the audit log.
 */
export function ReasonModal({
  visible,
  title,
  detail,
  label,
  placeholder,
  confirmLabel,
  minLength = 10,
  optional = false,
  danger = false,
  loading = false,
  onCancel,
  onConfirm,
}: {
  visible: boolean;
  title: string;
  detail?: string;
  label: string;
  placeholder?: string;
  confirmLabel: string;
  minLength?: number;
  optional?: boolean;
  danger?: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [text, setText] = useState('');

  useEffect(() => {
    if (visible) setText('');
  }, [visible]);

  const trimmed = text.trim();
  const tooShort = optional ? trimmed.length > 0 && trimmed.length < minLength : trimmed.length < minLength;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView
        style={styles.modalBackdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.modalCard}>
          <Text style={styles.modalTitle}>{title}</Text>
          {detail ? (
            <Text style={styles.modalDetail} numberOfLines={3}>
              {detail}
            </Text>
          ) : null}
          <Text style={styles.modalLabel}>{label}</Text>
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder={placeholder}
            placeholderTextColor={colors.dim}
            multiline
            maxLength={1000}
            style={styles.modalInput}
            autoFocus
          />
          {tooShort ? (
            <Text style={styles.modalHint}>At least {minLength} characters.</Text>
          ) : null}
          <View style={styles.modalActions}>
            <View style={styles.flex}>
              <Button label="Cancel" variant="secondary" onPress={onCancel} disabled={loading} />
            </View>
            <View style={styles.flex}>
              <Button
                label={confirmLabel}
                variant={danger ? 'danger' : 'primary'}
                onPress={() => onConfirm(trimmed)}
                disabled={tooShort}
                loading={loading}
              />
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export const adminStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  list: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge, gap: spacing.md },
  listEmpty: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: spacing.xl },
  footer: { paddingVertical: spacing.lg },
});

const styles = StyleSheet.create({
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
  },
  headerText: { flex: 1 },
  title: { ...typography.h1, color: colors.text },
  titleSmall: { ...typography.h3, color: colors.text },
  subtitle: { ...typography.caption, color: colors.sub },
  chipsScroll: { flexGrow: 0 },
  chips: { gap: spacing.sm, paddingHorizontal: spacing.xl, paddingBottom: spacing.md },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  chipActive: { backgroundColor: colors.gold, borderColor: colors.gold },
  chipText: { ...typography.caption, color: colors.sub },
  chipTextActive: { color: colors.bg, fontWeight: '600' },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.md,
    height: 44,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  searchInput: { flex: 1, ...typography.body, color: colors.text, paddingVertical: 0 },
  tag: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  tagText: { ...typography.tiny },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: spacing.md,
    paddingVertical: 6,
  },
  infoLabel: { ...typography.caption, color: colors.sub },
  infoValue: { ...typography.caption, color: colors.text, flexShrink: 1, textAlign: 'right' },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  sectionTitle: {
    ...typography.bodyBold,
    color: colors.text,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
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
