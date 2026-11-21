import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError } from '../../../api/client';
import { ErrorState, LoadingState } from '../../../components/feedback/States';
import { Avatar } from '../../../components/ui/Avatar';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { useAuthStore } from '../../../store/authStore';
import { colors, radius, spacing, typography } from '../../../theme';
import type { BuyerProfile, PhotographerSelfProfile } from '../../../types/models';
import {
  useDeleteAccount,
  useMyProfile,
  useUpdateProfile,
  useUpdateUser,
} from '../../shop/hooks/useShop';

/**
 * Full Edit Profile and Account Management Screen.
 * Available to ALL account types (Buyer, Photographer, etc.).
 *
 * Provides complete capabilities to:
 * 1. Update & Edit all user account information (name, phone, city, avatar).
 * 2. Update & Edit role-specific information (budget preferences for buyers, studio listing for photographers).
 * 3. Delete / Clear individual fields (remove avatar photo, clear phone, clear city, clear budget/bio).
 * 4. Permanently Delete Account and all associated personal information.
 */
export function EditProfileScreen({ onBack }: { onBack: () => void }) {
  const user = useAuthStore((s) => s.user);
  const isPhotographer = user?.role === 'PHOTOGRAPHER';

  const profile = useMyProfile();
  const updateProfile = useUpdateProfile();
  const updateUser = useUpdateUser();
  const deleteAccount = useDeleteAccount();

  const [form, setForm] = useState<Record<string, string> | null>(null);

  if (profile.isLoading) return <LoadingState label="Loading your profile…" />;
  if (profile.isError || !profile.data) {
    return (
      <ErrorState
        message={(profile.error as ApiError)?.message}
        onRetry={() => profile.refetch()}
      />
    );
  }

  const photographerData = isPhotographer
    ? (profile.data as PhotographerSelfProfile)
    : null;
  const buyerData = isPhotographer ? null : (profile.data as BuyerProfile);

  const initialValues: Record<string, string> = {
    // Common account fields
    full_name: user?.full_name ?? '',
    phone: user?.phone ?? '',
    city: user?.city ?? '',
    // Buyer-specific
    budget_min: buyerData?.budget_min
      ? String(Math.round(Number(buyerData.budget_min)))
      : '',
    budget_max: buyerData?.budget_max
      ? String(Math.round(Number(buyerData.budget_max)))
      : '',
    // Photographer-specific
    business_name: photographerData?.business_name ?? '',
    tagline: photographerData?.tagline ?? '',
    bio: photographerData?.bio ?? '',
    years_experience: String(photographerData?.years_experience ?? 0),
    service_radius_km: String(photographerData?.service_radius_km ?? 50),
    equipment: photographerData?.equipment ?? '',
    languages: photographerData?.languages ?? '',
    website: photographerData?.website ?? '',
    instagram: photographerData?.instagram ?? '',
  };

  const values = form ?? initialValues;

  const set = (key: string, value: string) =>
    setForm((prev) => ({ ...(prev ?? initialValues), [key]: value }));

  const confirmDeleteAvatar = () => {
    Alert.alert(
      'Remove Photo',
      'Are you sure you want to remove your profile photo?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            updateUser.mutate(
              { delete_avatar: true },
              {
                onSuccess: () => Alert.alert('Removed', 'Profile photo removed.'),
                onError: (err) =>
                  Alert.alert('Error', (err as ApiError).message),
              },
            );
          },
        },
      ],
    );
  };

  const save = () => {
    const fullName = values.full_name.trim();
    if (fullName.length < 3) {
      Alert.alert('Invalid Name', 'Full name must be at least 3 characters.');
      return;
    }

    if (isPhotographer && values.bio.trim() && values.bio.trim().length < 50) {
      Alert.alert(
        'Bio is too short',
        'A bio needs at least 50 characters to be useful to buyers — say what you shoot and how you work.',
      );
      return;
    }

    // 1. Update base user account information
    updateUser.mutate(
      {
        full_name: fullName,
        phone: values.phone.trim(),
        city: values.city.trim(),
      },
      {
        onError: (err) => {
          Alert.alert('Could not update account', (err as ApiError).message);
        },
        onSuccess: () => {
          // 2. Update role-specific profile details
          if (isPhotographer) {
            updateProfile.mutate(
              {
                business_name: values.business_name.trim(),
                tagline: values.tagline.trim(),
                bio: values.bio.trim(),
                years_experience: Number(values.years_experience) || 0,
                equipment: values.equipment.trim(),
                languages: values.languages.trim(),
                website: values.website.trim(),
                instagram: values.instagram.trim().replace(/^@/, ''),
                service_radius_km: Number(values.service_radius_km) || 50,
              },
              {
                onSuccess: () => {
                  setForm(null);
                  // Leave the editor once the save is acknowledged, so the
                  // screen does not look like editing is still in progress.
                  Alert.alert(
                    'Profile Saved',
                    'Your information has been updated successfully.',
                    [{ text: 'OK', onPress: onBack }],
                    { cancelable: true, onDismiss: onBack },
                  );
                },
                onError: (err) =>
                  Alert.alert('Could not save details', (err as ApiError).message),
              },
            );
          } else {
            // Buyer profile
            const minBudget = values.budget_min.trim() ? Number(values.budget_min) : null;
            const maxBudget = values.budget_max.trim() ? Number(values.budget_max) : null;

            if (minBudget !== null && maxBudget !== null && minBudget > maxBudget) {
              Alert.alert('Invalid Budget', 'Maximum budget cannot be less than minimum budget.');
              return;
            }

            updateProfile.mutate(
              {
                budget_min: minBudget,
                budget_max: maxBudget,
              },
              {
                onSuccess: () => {
                  setForm(null);
                  // Leave the editor once the save is acknowledged, so the
                  // screen does not look like editing is still in progress.
                  Alert.alert(
                    'Profile Saved',
                    'Your information has been updated successfully.',
                    [{ text: 'OK', onPress: onBack }],
                    { cancelable: true, onDismiss: onBack },
                  );
                },
                onError: (err) =>
                  Alert.alert('Could not save budget', (err as ApiError).message),
              },
            );
          }
        },
      },
    );
  };

  const confirmDeleteAccount = () => {
    Alert.alert(
      'Delete Account & Data?',
      'Are you sure you want to permanently delete your account and all associated personal data? You will be signed out immediately and this cannot be undone.',
      [
        { text: 'Keep Account', style: 'cancel' },
        {
          text: 'Delete Permanently',
          style: 'destructive',
          onPress: () => {
            deleteAccount.mutate('User requested account deletion from settings', {
              onSuccess: () => {
                Alert.alert('Account Deleted', 'Your account has been deleted.');
              },
              onError: (error) => {
                Alert.alert('Could not delete account', (error as ApiError).message);
              },
            });
          },
        },
      ],
    );
  };

  const isSaving = updateUser.isPending || updateProfile.isPending;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Go back">
          <Ionicons name="chevron-back" size={24} color={colors.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Edit Profile & Account</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {/* ─── Profile Avatar & Removal ────────────────────────────────────── */}
        <View style={styles.avatarSection}>
          <Avatar
            uri={user?.avatar_url}
            name={values.full_name || user?.full_name || '?'}
            size={76}
          />
          <View style={styles.avatarMeta}>
            <Text style={styles.avatarEmail}>{user?.email}</Text>
            <View style={styles.roleBadge}>
              <Text style={styles.roleBadgeText}>
                {isPhotographer ? 'Photographer Account' : 'Buyer Account'}
              </Text>
            </View>
            {user?.avatar_url ? (
              <Pressable
                onPress={confirmDeleteAvatar}
                style={styles.deletePhotoBtn}
                accessibilityRole="button"
                accessibilityLabel="Remove photo"
              >
                <Ionicons name="trash-outline" size={13} color={colors.red} />
                <Text style={styles.deletePhotoText}>Delete Photo</Text>
              </Pressable>
            ) : null}
          </View>
        </View>

        {/* ─── Personal Account Info (ALL Account Types) ───────────────────── */}
        <View style={styles.sectionHeaderRow}>
          <Text style={styles.section}>Account Information</Text>
        </View>

        <Input
          label="Full Name"
          placeholder="Your full name"
          value={values.full_name}
          onChangeText={(v) => set('full_name', v)}
          icon="person-outline"
        />

        <View style={styles.fieldWithAction}>
          <View style={styles.fieldInputFlex}>
            <Input
              label="Phone Number"
              placeholder="+923001234567"
              value={values.phone}
              onChangeText={(v) => set('phone', v)}
              keyboardType="phone-pad"
              icon="call-outline"
            />
          </View>
          {values.phone ? (
            <Pressable
              onPress={() => set('phone', '')}
              style={styles.clearFieldBtn}
              accessibilityRole="button"
              accessibilityLabel="Clear phone"
            >
              <Ionicons name="close-circle" size={16} color={colors.sub} />
              <Text style={styles.clearFieldText}>Clear</Text>
            </Pressable>
          ) : null}
        </View>

        <View style={styles.fieldWithAction}>
          <View style={styles.fieldInputFlex}>
            <Input
              label="City"
              placeholder="e.g. Lahore, Karachi, Islamabad"
              value={values.city}
              onChangeText={(v) => set('city', v)}
              icon="location-outline"
            />
          </View>
          {values.city ? (
            <Pressable
              onPress={() => set('city', '')}
              style={styles.clearFieldBtn}
              accessibilityRole="button"
              accessibilityLabel="Clear city"
            >
              <Ionicons name="close-circle" size={16} color={colors.sub} />
              <Text style={styles.clearFieldText}>Clear</Text>
            </Pressable>
          ) : null}
        </View>

        {/* ─── Role-Specific Section ───────────────────────────────────────── */}
        {isPhotographer ? (
          <>
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.section}>Public Studio Listing</Text>
            </View>

            {photographerData && !photographerData.is_approved ? (
              <View style={styles.notice}>
                <Ionicons name="hourglass-outline" size={16} color={colors.amber} />
                <Text style={styles.noticeText}>
                  {photographerData.rejection_reason ||
                    'Your profile is awaiting admin approval. Completing it helps get verified.'}
                </Text>
              </View>
            ) : null}

            <Input
              label="Business Name"
              placeholder="e.g. Zahid Photography"
              value={values.business_name}
              onChangeText={(v) => set('business_name', v)}
            />

            <Input
              label="Tagline"
              placeholder="e.g. Cinematic weddings and portraits"
              value={values.tagline}
              onChangeText={(v) => set('tagline', v)}
              maxLength={180}
            />

            <Input
              label="Bio"
              placeholder="Tell clients about your photography style and experience (min 50 chars)."
              value={values.bio}
              onChangeText={(v) => set('bio', v)}
              multiline
              numberOfLines={4}
              hint={`${values.bio.length} characters`}
            />

            <View style={styles.row}>
              <View style={styles.rowItem}>
                <Input
                  label="Years Experience"
                  value={values.years_experience}
                  onChangeText={(v) => set('years_experience', v.replace(/[^0-9]/g, ''))}
                  keyboardType="number-pad"
                />
              </View>
              <View style={styles.rowItem}>
                <Input
                  label="Travel Radius (km)"
                  value={values.service_radius_km}
                  onChangeText={(v) => set('service_radius_km', v.replace(/[^0-9]/g, ''))}
                  keyboardType="number-pad"
                />
              </View>
            </View>

            <Input
              label="Equipment"
              placeholder="e.g. Sony A7IV, 24-70mm GM, Godox flashes"
              value={values.equipment}
              onChangeText={(v) => set('equipment', v)}
              multiline
            />

            <Input
              label="Languages"
              placeholder="e.g. English, Urdu, Punjabi"
              value={values.languages}
              onChangeText={(v) => set('languages', v)}
            />

            <Input
              label="Website"
              placeholder="https://…"
              value={values.website}
              onChangeText={(v) => set('website', v)}
              autoCapitalize="none"
              keyboardType="url"
              icon="globe-outline"
            />

            <Input
              label="Instagram Handle"
              placeholder="yourhandle"
              value={values.instagram}
              onChangeText={(v) => set('instagram', v)}
              autoCapitalize="none"
              icon="logo-instagram"
            />
          </>
        ) : (
          <>
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.section}>Budget Preferences</Text>
              {(values.budget_min || values.budget_max) ? (
                <Pressable
                  onPress={() => {
                    set('budget_min', '');
                    set('budget_max', '');
                  }}
                  style={styles.clearBudgetBtn}
                >
                  <Text style={styles.clearBudgetText}>Clear Budget</Text>
                </Pressable>
              ) : null}
            </View>

            <Text style={styles.helperText}>
              Set or clear your price range to get personalized photographer recommendations.
            </Text>

            <View style={styles.row}>
              <View style={styles.rowItem}>
                <Input
                  label="Min Budget (PKR)"
                  placeholder="e.g. 15000"
                  value={values.budget_min}
                  onChangeText={(v) => set('budget_min', v.replace(/[^0-9]/g, ''))}
                  keyboardType="number-pad"
                />
              </View>
              <View style={styles.rowItem}>
                <Input
                  label="Max Budget (PKR)"
                  placeholder="e.g. 80000"
                  value={values.budget_max}
                  onChangeText={(v) => set('budget_max', v.replace(/[^0-9]/g, ''))}
                  keyboardType="number-pad"
                />
              </View>
            </View>
          </>
        )}

        {/* ─── Save Changes Button ─────────────────────────────────────────── */}
        <View style={styles.saveContainer}>
          <Button
            label="Save Changes"
            onPress={save}
            loading={isSaving}
          />
        </View>

        {/* ─── Danger Zone: Delete Account & All Information ───────────────── */}
        <View style={styles.dangerZone}>
          <View style={styles.dangerHeader}>
            <Ionicons name="warning-outline" size={18} color={colors.red} />
            <Text style={styles.dangerTitle}>Delete Account & Data</Text>
          </View>
          <Text style={styles.dangerDescription}>
            Permanently delete your profile, personal data, and account. Active bookings must be completed or cancelled before deleting. This cannot be undone.
          </Text>
          <Button
            label="Delete Account Permanently"
            variant="danger"
            onPress={confirmDeleteAccount}
            loading={deleteAccount.isPending}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
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
  headerSpacer: { width: 24 },
  content: { padding: spacing.xl, paddingBottom: spacing.huge, gap: spacing.md },
  avatarSection: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.lg,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  avatarMeta: { flex: 1, gap: 4 },
  avatarEmail: { ...typography.body, color: colors.text, fontWeight: '600' },
  roleBadge: {
    alignSelf: 'flex-start',
    backgroundColor: colors.card,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  roleBadgeText: { ...typography.tiny, color: colors.sub, fontSize: 11 },
  deletePhotoBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 4,
  },
  deletePhotoText: { ...typography.tiny, color: colors.red },
  sectionHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.md,
  },
  section: {
    ...typography.caption,
    color: colors.sub,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  helperText: {
    ...typography.tiny,
    color: colors.dim,
    marginTop: -spacing.xs,
  },
  fieldWithAction: {
    position: 'relative',
  },
  fieldInputFlex: {
    flex: 1,
  },
  clearFieldBtn: {
    position: 'absolute',
    right: 12,
    top: 38,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    padding: 4,
  },
  clearFieldText: {
    ...typography.tiny,
    color: colors.sub,
    fontSize: 11,
  },
  clearBudgetBtn: {
    paddingVertical: 2,
    paddingHorizontal: spacing.xs,
  },
  clearBudgetText: {
    ...typography.tiny,
    color: colors.red,
  },
  row: { flexDirection: 'row', gap: spacing.sm },
  rowItem: { flex: 1 },
  notice: {
    flexDirection: 'row',
    gap: spacing.sm,
    backgroundColor: colors.amberDim,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  noticeText: { ...typography.caption, color: colors.amber, flex: 1, lineHeight: 18 },
  saveContainer: {
    marginTop: spacing.lg,
  },
  dangerZone: {
    marginTop: spacing.xl,
    padding: spacing.lg,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.redDim,
    gap: spacing.sm,
  },
  dangerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  dangerTitle: {
    ...typography.caption,
    color: colors.red,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  dangerDescription: {
    ...typography.tiny,
    color: colors.sub,
    lineHeight: 16,
    marginBottom: spacing.xs,
  },
});
