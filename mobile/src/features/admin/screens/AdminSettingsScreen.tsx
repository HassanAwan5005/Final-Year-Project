import React, { useEffect, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { EmptyState, ErrorState, LoadingState } from '../../../components/feedback/States';
import { Button } from '../../../components/ui/Button';
import { colors, radius, spacing, typography } from '../../../theme';
import type { PlatformSetting } from '../../../types/models';
import { timeAgo } from '../../../utils/format';
import { AdminHeader, adminStyles, Card, SectionTitle } from '../components/AdminUI';
import { usePlatformSettings, useUpdateSetting } from '../hooks/useAdmin';

const GROUP_LABEL: Record<string, string> = {
  bookings: 'Bookings',
  money: 'Money',
  ai: 'Recommendations (AI)',
};

/**
 * The declared runtime settings. Only existing keys can be changed (the
 * server refuses new ones), each value is type-checked server-side, and every
 * change is written to the audit log with its old and new value.
 *
 * NOTE: the server does not read these rows yet — bookings, commission and
 * recommendations use the values in backend/config/settings/base.py. The
 * subtitle says so rather than implying a change takes effect.
 */
export function AdminSettingsScreen({ onBack }: { onBack: () => void }) {
  const settings = usePlatformSettings();

  const groups = new Map<string, PlatformSetting[]>();
  for (const setting of settings.data ?? []) {
    const list = groups.get(setting.group) ?? [];
    list.push(setting);
    groups.set(setting.group, list);
  }

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader
        title="Platform settings"
        subtitle="Saved and audited · not yet read by the server"
        onBack={onBack}
      />
      {settings.isLoading ? (
        <LoadingState label="Loading settings…" />
      ) : settings.isError ? (
        <ErrorState message={(settings.error as ApiError)?.message} onRetry={() => settings.refetch()} />
      ) : !settings.data?.length ? (
        <EmptyState icon="settings-outline" title="No settings" detail="Run the seed command to create them." />
      ) : (
        <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <ScrollView
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
            refreshControl={
              <RefreshControl
                refreshing={settings.isRefetching}
                onRefresh={() => {
                  settings.refetch();
                }}
                tintColor={colors.gold}
              />
            }
          >
            {[...groups.entries()].map(([group, rows]) => (
              <View key={group}>
                <SectionTitle>{GROUP_LABEL[group] ?? (group || 'General')}</SectionTitle>
                <View style={styles.group}>
                  {rows.map((setting) => (
                    <SettingRow key={setting.key} setting={setting} />
                  ))}
                </View>
              </View>
            ))}
          </ScrollView>
        </KeyboardAvoidingView>
      )}
    </SafeAreaView>
  );
}

function SettingRow({ setting }: { setting: PlatformSetting }) {
  const update = useUpdateSetting();
  const [draft, setDraft] = useState(setting.value);

  // Keep the field in step with the server after a save or a refresh.
  useEffect(() => setDraft(setting.value), [setting.value]);

  const save = (value: string) =>
    update.mutate(
      { key: setting.key, value },
      {
        onSuccess: () => Alert.alert('Saved', `${setting.label || setting.key} updated.`),
        onError: (error) => {
          setDraft(setting.value);
          Alert.alert('Could not save', (error as ApiError)?.message ?? 'Please try again.');
        },
      },
    );

  const isBool = setting.value_type === 'BOOL';
  const isNumber = setting.value_type === 'INT' || setting.value_type === 'FLOAT';
  const changed = draft.trim() !== setting.value;

  return (
    <Card>
      <View style={styles.rowTop}>
        <View style={styles.flex}>
          <Text style={styles.label}>{setting.label || setting.key}</Text>
          <Text style={styles.key}>{setting.key}</Text>
        </View>
        {isBool ? (
          <Switch
            value={['true', '1', 'yes'].includes(setting.value.toLowerCase())}
            onValueChange={(on) => save(on ? 'true' : 'false')}
            disabled={update.isPending}
            trackColor={{ true: colors.gold, false: colors.border }}
          />
        ) : null}
      </View>
      {setting.description ? <Text style={styles.description}>{setting.description}</Text> : null}

      {!isBool ? (
        <View style={styles.editRow}>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            keyboardType={isNumber ? 'decimal-pad' : 'default'}
            style={styles.input}
            placeholderTextColor={colors.dim}
            autoCapitalize="none"
            autoCorrect={false}
          />
          <Button
            label="Save"
            size="sm"
            fullWidth={false}
            onPress={() => save(draft.trim())}
            disabled={!changed || !draft.trim()}
            loading={update.isPending}
          />
        </View>
      ) : null}

      {setting.updated_by_name ? (
        <Text style={styles.updated}>
          Last changed by {setting.updated_by_name} · {timeAgo(setting.updated_at)}
        </Text>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { paddingHorizontal: spacing.xl, paddingBottom: spacing.huge },
  group: { gap: spacing.sm },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  label: { ...typography.bodyBold, color: colors.text },
  key: { ...typography.tiny, color: colors.dim },
  description: { ...typography.caption, color: colors.sub },
  editRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.sm },
  input: {
    flex: 1,
    ...typography.body,
    color: colors.text,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    height: 40,
  },
  updated: { ...typography.tiny, color: colors.sub, marginTop: spacing.xs },
});
