import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';
import React, { useCallback, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { photographersApi, recommendationsApi } from '../../../api/services/photographers.api';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { useCurrentUser } from '../../../store/authStore';
import type { Category, PhotographerSummary, Recommendation } from '../../../types/models';
import { colors, radius, spacing, typography } from '../../../theme';
import { useChatUnreadTotal } from '../../chat/hooks/useChat';
import { NotificationBell } from '../../notifications/components/NotificationBell';
import { PhotographerCard } from '../components/PhotographerCard';
import {
  useCategories,
  useRecommendations,
  useTrendingPhotographers,
} from '../hooks/usePhotographers';

interface Props {
  onOpenPhotographer: (id: number) => void;
  onOpenCategory: (slug: string) => void;
  onOpenSearch: () => void;
  /**
   * Notifications and Messages live in this header rather than in bottom tabs.
   *
   * Six bottom tabs is past the point where labels truncate on a small Android
   * device (the same reason selling sits inside Profile), and both of these are
   * glanceable badges rather than destinations people navigate to repeatedly.
   */
  onOpenNotifications?: () => void;
  onOpenMessages?: () => void;
}

export function HomeScreen({
  onOpenPhotographer,
  onOpenCategory,
  onOpenNotifications,
  onOpenMessages,
}: Props) {
  const user = useCurrentUser();
  const [refreshing, setRefreshing] = useState(false);
  const chatUnread = useChatUnreadTotal();

  const recommendations = useRecommendations({ limit: 50 });
  const categories = useCategories();
  const trending = useTrendingPhotographers(user?.city);
  const isBuyer = user?.role === 'BUYER';

  // Coming back from a photographer's profile: the personalised list follows
  // the city of the profiles the buyer has been viewing, so ask again. Cheap —
  // the server answers from its cache unless that city actually changed. The
  // first focus is skipped because the query has only just loaded.
  const refetchFeed = recommendations.refetch;
  const firstFocus = useRef(true);
  useFocusEffect(
    useCallback(() => {
      if (firstFocus.current) {
        firstFocus.current = false;
        return;
      }
      if (isBuyer) refetchFeed();
    }, [isBuyer, refetchFeed]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([
      recommendations.refetch(),
      trending.refetch(),
    ]);
    setRefreshing(false);
  }, [recommendations, trending]);

  const openPhotographer = useCallback(
    (id: number, fromRecommendation: boolean) => {
      // Close the feedback loop before navigating. Fire-and-forget — the
      // click is analytics, and it must never delay the screen transition.
      if (fromRecommendation) recommendationsApi.click(id);
      onOpenPhotographer(id);
    },
    [onOpenPhotographer],
  );

  // ─── AI search: Matchmaker (typed request) + visual search (photo) ─────────
  // Both run on the server against the signed-in buyer, so results are
  // personalised the same way as the "Picked for you" feed.
  const [aiQuery, setAiQuery] = useState('');
  const [aiLoading, setAiLoading] = useState<'matchmaker' | 'visual' | null>(null);
  const [aiResult, setAiResult] = useState<{
    kind: 'matchmaker' | 'visual';
    message: string;
    image?: string;
    photographers: Recommendation[];
  } | null>(null);

  const clearAiSearch = useCallback(() => {
    setAiResult(null);
    setAiQuery('');
  }, []);

  const runMatchmaker = useCallback(async () => {
    const prompt = aiQuery.trim();
    if (!prompt) return;
    try {
      setAiLoading('matchmaker');
      const res = await photographersApi.matchmaker(prompt, {});
      setAiResult({
        kind: 'matchmaker',
        message: res.assistantMessage,
        photographers: res.photographers,
      });
    } catch (err: any) {
      Alert.alert('Matchmaker', err?.message || 'Could not find matchmaker suggestions.');
    } finally {
      setAiLoading(null);
    }
  }, [aiQuery]);

  const runVisualSearch = useCallback(async () => {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Permission needed', 'Please allow photo library access to search by photo.');
        return;
      }
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        quality: 0.8,
      });
      if (picked.canceled || !picked.assets?.[0]?.uri) return;

      const uri = picked.assets[0].uri;
      setAiLoading('visual');
      const res = await photographersApi.visualSearch(uri, {});
      setAiResult({
        kind: 'visual',
        message: res.referenceStyle
          ? `Style: ${res.referenceStyle}`
          : 'Photographers with a similar style',
        image: uri,
        photographers: res.items,
      });
    } catch (err: any) {
      Alert.alert('Visual Search Error', err?.message || 'Failed to match visual style.');
    } finally {
      setAiLoading(null);
    }
  }, []);

  if (recommendations.isLoading && !recommendations.data) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <LoadingState label="Finding photographers for you…" />
      </SafeAreaView>
    );
  }

  if (recommendations.isError && !recommendations.data) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <ErrorState
          message={(recommendations.error as Error)?.message}
          onRetry={() => recommendations.refetch()}
        />
      </SafeAreaView>
    );
  }

  const feed = recommendations.data;

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.gold}
          />
        }
      >
        {/* ─── Header ──────────────────────────────────────────────────── */}
        <View style={styles.header}>
          <View style={styles.headerText}>
            <Text style={styles.greeting}>
              {greetingFor(new Date())}, {user?.full_name?.split(' ')[0] ?? 'there'}
            </Text>
            <Text style={styles.headline}>Find your photographer</Text>
          </View>
          <View style={styles.headerActions}>
            {onOpenMessages ? (
              <NotificationBell
                onPress={onOpenMessages}
                icon="chatbubbles-outline"
                count={chatUnread.data?.unread_total ?? 0}
              />
            ) : null}
            {onOpenNotifications ? (
              <NotificationBell onPress={onOpenNotifications} />
            ) : null}
          </View>
        </View>

        {/* ─── AI search (Matchmaker + visual search) ──────────────────── */}
        <View style={styles.searchBar}>
          <Ionicons name="sparkles" size={17} color={colors.gold} />
          <TextInput
            value={aiQuery}
            onChangeText={setAiQuery}
            placeholder="Ask AI (e.g. Mehndi in Lahore under 40k)"
            placeholderTextColor={colors.dim}
            style={styles.searchInput}
            returnKeyType="search"
            onSubmitEditing={runMatchmaker}
            accessibilityLabel="Ask the AI matchmaker"
          />
          {aiQuery.length > 0 ? (
            <Pressable onPress={clearAiSearch} hitSlop={8}>
              <Ionicons name="close-circle" size={17} color={colors.dim} />
            </Pressable>
          ) : null}
          <Pressable
            onPress={runVisualSearch}
            hitSlop={6}
            accessibilityLabel="Search by photo"
          >
            <Ionicons name="camera-outline" size={20} color={colors.gold} />
          </Pressable>
          {aiQuery.trim().length > 3 ? (
            <Pressable
              onPress={runMatchmaker}
              style={styles.aiMatchButton}
              accessibilityLabel="AI Matchmaker"
            >
              <Ionicons name="sparkles" size={13} color={colors.bg} />
              <Text style={styles.aiMatchText}>Match</Text>
            </Pressable>
          ) : null}
        </View>

        {/* ─── AI search results ───────────────────────────────────────── */}
        {aiLoading ? (
          <View style={styles.aiLoadingBox}>
            <ActivityIndicator color={colors.gold} />
            <Text style={styles.aiLoadingText}>
              {aiLoading === 'visual'
                ? 'Extracting visual aesthetic embedding…'
                : 'Parsing requirements & matching pros…'}
            </Text>
          </View>
        ) : aiResult ? (
          <>
            <SectionHeader
              title={aiResult.kind === 'visual' ? 'Matched by photo' : 'AI Matchmaker'}
              badge="AI"
            />
            <View style={styles.aiCard}>
              {aiResult.image ? (
                <Image source={{ uri: aiResult.image }} style={styles.aiThumb} />
              ) : null}
              <View style={styles.aiCardInfo}>
                <Text style={styles.aiCardMsg}>{aiResult.message}</Text>
                <Text style={styles.aiCardSub}>
                  {aiResult.photographers.length} match
                  {aiResult.photographers.length === 1 ? '' : 'es'} found
                </Text>
              </View>
              <Pressable onPress={clearAiSearch} hitSlop={10} accessibilityLabel="Clear AI search">
                <Ionicons name="close" size={18} color={colors.sub} />
              </Pressable>
            </View>
            <View style={styles.list}>
              {aiResult.photographers.map((photographer, index) => (
                <PhotographerCard
                  key={`ai-${photographer.id}-${index}`}
                  photographer={photographer}
                  showReason
                  onPress={() => openPhotographer(photographer.id, false)}
                />
              ))}
            </View>
          </>
        ) : null}

        {/* ─── Categories ──────────────────────────────────────────────── */}
        <SectionHeader title="Browse by event" />
        <FlatList
          horizontal
          data={categories.data ?? []}
          keyExtractor={(item: Category) => item.slug}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipRow}
          renderItem={({ item }) => (
            <Pressable
              onPress={() => onOpenCategory(item.slug)}
              style={({ pressed }) => [styles.categoryChip, pressed && styles.chipPressed]}
            >
              <Text style={styles.categoryName}>{item.name}</Text>
              <Text style={styles.categoryCount}>
                {item.photographer_count} pros
              </Text>
            </Pressable>
          )}
        />

        {/* ─── AI recommendations ──────────────────────────────────────── */}
        <SectionHeader
          title={feed?.personalised ? 'Picked for you' : 'Top rated'}
          badge={feed?.personalised ? 'PERSONALISED' : undefined}
        />

        {/*
          When the engine had to widen the filters it says so. Silently
          showing near-matches as if they were exact matches is the kind of
          small dishonesty that erodes trust in the whole feature.
        */}
        {feed?.relaxed ? (
          <View style={styles.relaxedNotice}>
            <Ionicons name="information-circle-outline" size={14} color={colors.amber} />
            <Text style={styles.relaxedText}>
              No exact matches — {feed.relaxed}.
            </Text>
          </View>
        ) : null}

        <View style={styles.list}>
          {(feed?.items ?? []).map((photographer, index) => (
            <PhotographerCard
              key={`rec-${photographer.id}-${index}`}
              photographer={photographer}
              showReason
              onPress={() => openPhotographer(photographer.id, true)}
            />
          ))}
        </View>

        {/* ─── Trending ────────────────────────────────────────────────── */}
        {trending.data && trending.data.length > 0 ? (
          <>
            <SectionHeader
              title={user?.city ? `Trending in ${user.city}` : 'Trending now'}
            />
            <FlatList
              horizontal
              data={trending.data}
              keyExtractor={(item: PhotographerSummary, index: number) => `trend-${item.id}-${index}`}
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.chipRow}
              renderItem={({ item }) => (
                <MiniCard
                  photographer={item}
                  onPress={() => openPhotographer(item.id, false)}
                />
              )}
            />
          </>
        ) : null}

        {/* Engine transparency — genuinely useful during the FYP demo. */}
        {feed ? (
          <Text style={styles.engineNote}>
            Ranked by {feed.strategy.toLowerCase()} strategy
            {feed.modelMode !== 'none' ? ` · model: ${feed.modelMode}` : ''}
          </Text>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function greetingFor(date: Date): string {
  const hour = date.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

function SectionHeader({ title, badge }: { title: string; badge?: string }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {badge ? (
        <View style={styles.badge}>
          <Ionicons name="sparkles" size={9} color={colors.bg} />
          <Text style={styles.badgeText}>{badge}</Text>
        </View>
      ) : null}
    </View>
  );
}

function MiniCard({
  photographer,
  onPress,
}: {
  photographer: PhotographerSummary;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.miniCard, pressed && styles.chipPressed]}
    >
      <Text style={styles.miniName} numberOfLines={1}>
        {photographer.display_name}
      </Text>
      <Text style={styles.miniMeta} numberOfLines={1}>
        {photographer.city}
      </Text>
      <View style={styles.miniFooter}>
        <Ionicons name="star" size={11} color={colors.gold} />
        <Text style={styles.miniRating}>
          {parseFloat(photographer.avg_rating).toFixed(1)}
        </Text>
        <Text style={styles.miniBookings}>
          · {photographer.completed_bookings} shoots
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  content: { paddingBottom: spacing.huge },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
    paddingBottom: spacing.lg,
  },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  headerText: { gap: 2, flex: 1 },
  greeting: { ...typography.caption, color: colors.sub },
  headline: { ...typography.h1, color: colors.text },
  searchBar: {
    marginHorizontal: spacing.xl,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    minHeight: 46,
  },
  searchInput: { flex: 1, ...typography.body, color: colors.text, paddingVertical: spacing.xs },
  aiMatchButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.gold,
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
    borderRadius: radius.pill,
  },
  aiMatchText: { fontSize: 11, fontWeight: '700', color: colors.bg },
  aiLoadingBox: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.sm,
  },
  aiLoadingText: { ...typography.caption, color: colors.sub },
  aiCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.card,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.gold,
  },
  aiThumb: { width: 48, height: 48, borderRadius: radius.sm },
  aiCardInfo: { flex: 1, gap: 2 },
  aiCardMsg: { ...typography.body, fontSize: 13, color: colors.text, lineHeight: 18 },
  aiCardSub: { ...typography.tiny, color: colors.sub },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.xl,
    marginTop: spacing.xxl,
    marginBottom: spacing.md,
  },
  sectionTitle: { ...typography.h3, color: colors.text },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.gold,
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: radius.sm,
  },
  badgeText: {
    fontSize: 8,
    fontWeight: '800',
    color: colors.bg,
    letterSpacing: 0.4,
  },
  chipRow: {
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.xs,
    gap: spacing.md,
  },
  categoryChip: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    minWidth: 104,
  },
  chipPressed: { backgroundColor: colors.cardHover, borderColor: colors.gold },
  categoryName: { ...typography.bodyBold, color: colors.text },
  categoryCount: { ...typography.tiny, color: colors.sub, marginTop: 2 },
  list: { paddingHorizontal: spacing.xl },
  relaxedNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.amberDim,
    borderRadius: radius.md,
  },
  relaxedText: { ...typography.tiny, color: colors.amber, flex: 1 },
  miniCard: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.lg,
    width: 158,
    gap: 3,
  },
  miniName: { ...typography.bodyBold, color: colors.text, fontSize: 14 },
  miniMeta: { ...typography.tiny, color: colors.sub },
  miniFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    marginTop: spacing.sm,
  },
  miniRating: { ...typography.tiny, color: colors.text, fontWeight: '700' },
  miniBookings: { ...typography.tiny, color: colors.sub },
  engineNote: {
    ...typography.tiny,
    color: colors.dim,
    textAlign: 'center',
    marginTop: spacing.xxl,
  },
});
