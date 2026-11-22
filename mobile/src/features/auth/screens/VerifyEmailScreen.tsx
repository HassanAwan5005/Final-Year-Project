import { zodResolver } from '@hookform/resolvers/zod';
import React, { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { ApiError, api, unwrap } from '../../../api/client';
import { ENDPOINTS } from '../../../api/config';
import { Screen } from '../../../components/layout/Screen';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { useAuthStore } from '../../../store/authStore';
import { colors, radius, spacing, typography } from '../../../theme';
import type { User } from '../../../types/models';
import { otpSchema, type OtpForm } from '../schemas';

/**
 * Enter the 6-digit code emailed to the signed-in user.
 *
 * Shown right after sign-up, when a code is already on its way, and from the
 * Profile tab, where the user asks for one first.
 */
export function VerifyEmailScreen({
  codeAlreadySent,
  closeLabel,
  onClose,
}: {
  codeAlreadySent: boolean;
  closeLabel: string;
  onClose: () => void;
}) {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);

  const [sent, setSent] = useState(codeAlreadySent);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<OtpForm>({
    resolver: zodResolver(otpSchema),
    defaultValues: { code: '' },
  });

  const run = async (action: () => Promise<void>, fallback: string) => {
    setSubmitting(true);
    setFormError(null);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : fallback);
    } finally {
      setSubmitting(false);
    }
  };

  const sendCode = () =>
    run(async () => {
      await api.post(ENDPOINTS.auth.resendOtp, {});
      form.reset({ code: '' });
      setSent(true);
      setNotice('A new code has been sent.');
    }, 'Could not send the code. Try again.');

  const verify = (values: OtpForm) =>
    run(async () => {
      const verified = await unwrap<User>(
        api.post(ENDPOINTS.auth.verifyEmail, { code: values.code.trim() }),
      );
      setUser(verified);
      onClose();
    }, 'Could not verify the code. Try again.');

  return (
    <Screen scroll>
      <Text style={styles.title}>Verify your email</Text>
      <Text style={styles.subtitle}>
        {sent
          ? `Enter the 6-digit code sent to ${user?.email ?? 'your email'}. It expires in 15 minutes.`
          : `We will email a 6-digit code to ${user?.email ?? 'you'}.`}
      </Text>

      {formError ? (
        <View style={styles.banner}>
          <Text style={styles.bannerText}>{formError}</Text>
        </View>
      ) : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      {sent ? (
        <>
          <Controller
            control={form.control}
            name="code"
            render={({ field: { onChange, onBlur, value } }) => (
              <Input
                label="6-digit code"
                icon="keypad-outline"
                placeholder="000000"
                value={value}
                onChangeText={onChange}
                onBlur={onBlur}
                error={form.formState.errors.code?.message}
                keyboardType="number-pad"
                maxLength={6}
              />
            )}
          />
          <Button
            label="Verify email"
            onPress={form.handleSubmit(verify)}
            loading={submitting}
            size="lg"
          />
          <TouchableOpacity onPress={sendCode} disabled={submitting} style={styles.link}>
            <Text style={styles.linkText}>Resend code</Text>
          </TouchableOpacity>
        </>
      ) : (
        <>
          <Button label="Send code" onPress={sendCode} loading={submitting} size="lg" />
          <TouchableOpacity
            onPress={() => {
              setFormError(null);
              setSent(true);
            }}
            disabled={submitting}
            style={styles.link}
          >
            <Text style={styles.linkText}>I already have a code</Text>
          </TouchableOpacity>
        </>
      )}

      <TouchableOpacity onPress={onClose} disabled={submitting} style={styles.link}>
        <Text style={styles.closeText}>{closeLabel}</Text>
      </TouchableOpacity>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: {
    ...typography.h1,
    color: colors.text,
    marginTop: spacing.xxxl,
    marginBottom: spacing.sm,
  },
  subtitle: { ...typography.body, color: colors.sub, marginBottom: spacing.xxl },
  banner: {
    backgroundColor: colors.redDim,
    borderColor: colors.red,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  bannerText: { ...typography.caption, color: colors.red },
  notice: { ...typography.caption, color: colors.green, marginBottom: spacing.lg },
  link: { alignSelf: 'center', marginTop: spacing.lg, padding: spacing.sm },
  linkText: { ...typography.caption, color: colors.gold, fontWeight: '600' },
  closeText: { ...typography.caption, color: colors.sub, fontWeight: '600' },
});
