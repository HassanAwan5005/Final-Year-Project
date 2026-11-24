import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useAuthStore } from '../../../store/authStore';
import { colors, spacing, typography } from '../../../theme';
import { AdminHeader, adminStyles, Card } from '../components/AdminUI';

/** The fifth tab: audit log, platform settings, broadcasts, and log out. */
export function AdminMoreScreen({
  onOpenAudit,
  onOpenSettings,
  onOpenBroadcasts,
}: {
  onOpenAudit: () => void;
  onOpenSettings: () => void;
  onOpenBroadcasts: () => void;
}) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const confirmLogout = () =>
    Alert.alert('Log out?', undefined, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Log out', style: 'destructive', onPress: () => logout() },
    ]);

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader title="More" subtitle={user ? `Signed in as ${user.email}` : undefined} />
      <ScrollView contentContainerStyle={styles.content}>
        <Card style={styles.menu}>
          <MenuRow
            icon="document-text-outline"
            title="Audit log"
            detail="Every admin action, who did it and why"
            onPress={onOpenAudit}
          />
          <View style={styles.divider} />
          <MenuRow
            icon="settings-outline"
            title="Platform settings"
            detail="Booking rules, commission, recommendation weights"
            onPress={onOpenSettings}
          />
          <View style={styles.divider} />
          <MenuRow
            icon="megaphone-outline"
            title="Broadcasts"
            detail="Send an announcement to users"
            onPress={onOpenBroadcasts}
          />
        </Card>

        <Card style={styles.menu}>
          <MenuRow icon="log-out-outline" title="Log out" danger onPress={confirmLogout} />
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

function MenuRow({
  icon,
  title,
  detail,
  danger = false,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  detail?: string;
  danger?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={styles.row} accessibilityRole="button" accessibilityLabel={title}>
      <Ionicons name={icon} size={22} color={danger ? colors.red : colors.gold} />
      <View style={styles.rowBody}>
        <Text style={[styles.rowTitle, danger && { color: colors.red }]}>{title}</Text>
        {detail ? <Text style={styles.rowDetail}>{detail}</Text> : null}
      </View>
      {danger ? null : <Ionicons name="chevron-forward" size={18} color={colors.sub} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge, gap: spacing.lg },
  menu: { paddingVertical: spacing.xs },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: spacing.md },
  rowBody: { flex: 1 },
  rowTitle: { ...typography.bodyBold, color: colors.text },
  rowDetail: { ...typography.caption, color: colors.sub },
  divider: { height: 1, backgroundColor: colors.border },
});
