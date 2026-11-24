import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { Button } from '../../../components/ui/Button';
import { colors, radius, spacing, typography } from '../../../theme';
import type { Broadcast, BroadcastAudience } from '../../../types/models';
import { formatDate, timeAgo } from '../../../utils/format';
import { AdminHeader, adminStyles, Card, FilterChips, SectionTitle, Tag } from '../components/AdminUI';
import { useBroadcasts, useSendBroadcast } from '../hooks/useAdmin';

const AUDIENCES: { value: BroadcastAudience; label: string }[] = [
  { value: 'ALL', label: 'Everyone' },
  { value: 'BUYERS', label: 'Buyers' },
  { value: 'PHOTOGRAPHERS', label: 'Photographers' },
  { value: 'CITY', label: 'One city' },
];

const AUDIENCE_LABEL: Record<BroadcastAudience, string> = {
  ALL: 'Everyone',
  BUYERS: 'Buyers',
  PHOTOGRAPHERS: 'Photographers',
  CITY: 'City',
};

/**
 * Write an announcement and see past ones. Each recipient gets it in their
 * in-app notifications; the audit log records who sent it and to whom.
 */
export function AdminBroadcastsScreen({ onBack }: { onBack: () => void }) {
  const history = useBroadcasts();
  const send = useSendBroadcast();

  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState<BroadcastAudience>('ALL');
  const [city, setCity] = useState('');

  const rows = history.data?.pages.flatMap((page) => page.items) ?? [];
  const ready =
    title.trim().length >= 3 && body.trim().length >= 5 && (audience !== 'CITY' || city.trim().length > 0);

  const submit = () => {
    const who = audience === 'CITY' ? `users in ${city.trim()}` : AUDIENCE_LABEL[audience].toLowerCase();
    Alert.alert('Send this announcement?', `It goes to ${who} right away and cannot be unsent.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Send',
        onPress: () =>
          send.mutate(
            { title: title.trim(), body: body.trim(), audience, city_filter: city, send_push: true },
            {
              onSuccess: () => {
                setTitle('');
                setBody('');
                setCity('');
                setAudience('ALL');
                Alert.alert('Sent', 'The announcement is on its way.');
              },
              onError: (error) =>
                Alert.alert('Could not send', (error as ApiError)?.message ?? 'Please try again.'),
            },
          ),
      },
    ]);
  };

  const form = (
    <View>
      <Card style={styles.form}>
        <Text style={styles.label}>Title</Text>
        <TextInput
          value={title}
          onChangeText={setTitle}
          maxLength={160}
          placeholder="e.g. Eid booking rush — book early"
          placeholderTextColor={colors.dim}
          style={styles.input}
        />
        <Text style={styles.label}>Message</Text>
        <TextInput
          value={body}
          onChangeText={setBody}
          maxLength={1000}
          multiline
          placeholder="What do you want users to know?"
          placeholderTextColor={colors.dim}
          style={[styles.input, styles.multiline]}
        />
        <Text style={styles.label}>Send to</Text>
      </Card>
      <View style={styles.audience}>
        <FilterChips options={AUDIENCES} value={audience} onChange={setAudience} />
      </View>
      {audience === 'CITY' ? (
        <TextInput
          value={city}
          onChangeText={setCity}
          maxLength={80}
          placeholder="City name, e.g. Lahore"
          placeholderTextColor={colors.dim}
          style={[styles.input, styles.cityInput]}
        />
      ) : null}
      <Button label="Send announcement" onPress={submit} disabled={!ready} loading={send.isPending} />
      <SectionTitle>Sent before</SectionTitle>
    </View>
  );

  return (
    <SafeAreaView style={adminStyles.safe} edges={['top', 'left', 'right']}>
      <AdminHeader title="Broadcasts" subtitle="Announcements to your users" onBack={onBack} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {history.isLoading ? (
          <LoadingState label="Loading…" />
        ) : history.isError ? (
          <ErrorState message={(history.error as ApiError)?.message} onRetry={() => history.refetch()} />
        ) : (
          <FlatList
            data={rows}
            keyExtractor={(item) => String(item.id)}
            ListHeaderComponent={form}
            contentContainerStyle={adminStyles.list}
            keyboardShouldPersistTaps="handled"
            refreshControl={
              <RefreshControl
                refreshing={history.isRefetching && !history.isFetchingNextPage}
                onRefresh={() => {
                  history.refetch();
                }}
                tintColor={colors.gold}
              />
            }
            onEndReached={() => {
              if (history.hasNextPage && !history.isFetchingNextPage) history.fetchNextPage();
            }}
            onEndReachedThreshold={0.4}
            ListFooterComponent={
              history.isFetchingNextPage ? (
                <ActivityIndicator color={colors.gold} style={adminStyles.footer} />
              ) : undefined
            }
            ListEmptyComponent={<Text style={styles.empty}>No announcements sent yet.</Text>}
            renderItem={({ item }) => <BroadcastRow broadcast={item} />}
          />
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function BroadcastRow({ broadcast }: { broadcast: Broadcast }) {
  return (
    <Card>
      <View style={styles.rowTop}>
        <Tag
          label={
            broadcast.audience === 'CITY' && broadcast.city_filter
              ? `City: ${broadcast.city_filter}`
              : AUDIENCE_LABEL[broadcast.audience] ?? broadcast.audience
          }
          tone="gold"
        />
        <Text style={styles.meta}>{timeAgo(broadcast.created_at)}</Text>
      </View>
      <Text style={styles.title}>{broadcast.title}</Text>
      <Text style={styles.body}>{broadcast.body}</Text>
      <Text style={styles.meta}>
        {broadcast.sent_at
          ? `Delivered to ${broadcast.recipient_count} user${broadcast.recipient_count === 1 ? '' : 's'} · ${formatDate(broadcast.sent_at)}`
          : 'Waiting to be delivered'}
      </Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  form: { gap: spacing.xs },
  label: { ...typography.caption, color: colors.sub, marginTop: spacing.sm },
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
  multiline: { minHeight: 90, textAlignVertical: 'top' },
  audience: { marginHorizontal: -spacing.xl, marginTop: spacing.md },
  cityInput: { marginBottom: spacing.md },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { ...typography.bodyBold, color: colors.text, marginTop: spacing.xs },
  body: { ...typography.caption, color: colors.text },
  meta: { ...typography.tiny, color: colors.sub },
  empty: { ...typography.caption, color: colors.sub, textAlign: 'center' },
});
