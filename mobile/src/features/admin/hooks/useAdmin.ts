/** React Query hooks for the admin screens. */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { qk } from '../../../api/queryKeys';
import {
  adminApi,
  type AdminBookingFilters,
  type AdminFlagFilters,
  type AdminUserFilters,
  type NewBroadcast,
} from '../../../api/services/admin.api';
import type { Paginated } from '../../../api/services/photographers.api';

const nextPage = <T,>(last: Paginated<T>) => (last.hasNext ? last.page + 1 : undefined);

/**
 * After any admin action, everything admin-side is refetched (counts on the
 * dashboard, the lists, the audit log). Admin data is small and changes rarely,
 * so a broad refresh is simpler and never shows a stale badge.
 */
function useRefreshAdmin() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: qk.admin.all });
}

// ─── Dashboard ─────────────────────────────────────────────────────────────
export function useAdminDashboard() {
  return useQuery({
    queryKey: qk.admin.dashboard,
    queryFn: () => adminApi.dashboard(30),
    staleTime: 30_000,
  });
}

// ─── Users ─────────────────────────────────────────────────────────────────
export function useAdminUsers(filters: AdminUserFilters) {
  return useInfiniteQuery({
    queryKey: qk.admin.users(filters),
    queryFn: ({ pageParam }) => adminApi.users(filters, pageParam as number),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });
}

export function useAdminUser(id: number) {
  return useQuery({
    queryKey: qk.admin.user(id),
    queryFn: () => adminApi.user(id),
  });
}

export function useBlockUser() {
  const refresh = useRefreshAdmin();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      adminApi.blockUser(id, reason),
    onSuccess: refresh,
    retry: false,
  });
}

export function useUnblockUser() {
  const refresh = useRefreshAdmin();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      adminApi.unblockUser(id, reason),
    onSuccess: refresh,
    retry: false,
  });
}

// ─── Reports & flags ───────────────────────────────────────────────────────
export function useAdminFlags(filters: AdminFlagFilters) {
  return useInfiniteQuery({
    queryKey: qk.admin.flags(filters),
    queryFn: ({ pageParam }) => adminApi.flags(filters, pageParam as number),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });
}

export function useClaimFlag() {
  const refresh = useRefreshAdmin();
  return useMutation({
    mutationFn: (id: number) => adminApi.claimFlag(id),
    onSuccess: refresh,
    retry: false,
  });
}

export function useResolveFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      action,
      note,
    }: {
      id: number;
      action: 'ACTIONED' | 'DISMISSED';
      note: string;
    }) => adminApi.resolveFlag(id, action, note),
    onSuccess: () => {
      // Actioning can hide a review or pull an ad, so public lists refresh too.
      queryClient.invalidateQueries({ queryKey: qk.admin.all });
      queryClient.invalidateQueries({ queryKey: qk.shop.all });
      queryClient.invalidateQueries({ queryKey: qk.reviews.all });
    },
    retry: false,
  });
}

// ─── Bookings ──────────────────────────────────────────────────────────────
export function useAdminBookings(filters: AdminBookingFilters) {
  return useInfiniteQuery({
    queryKey: qk.admin.bookings(filters),
    queryFn: ({ pageParam }) => adminApi.bookings(filters, pageParam as number),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });
}

export function useAdminBooking(id: number) {
  return useQuery({
    queryKey: qk.admin.booking(id),
    queryFn: () => adminApi.booking(id),
  });
}

export function useForceCancelBooking() {
  const refresh = useRefreshAdmin();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      adminApi.forceCancelBooking(id, reason),
    onSuccess: refresh,
    retry: false,
  });
}

// ─── Audit log · settings · broadcasts ─────────────────────────────────────
export function useAuditLog(filters: { action?: string }) {
  return useInfiniteQuery({
    queryKey: qk.admin.audit(filters),
    queryFn: ({ pageParam }) => adminApi.audit(filters, pageParam as number),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });
}

export function usePlatformSettings() {
  return useQuery({
    queryKey: qk.admin.settings,
    queryFn: () => adminApi.settings(),
  });
}

export function useUpdateSetting() {
  const refresh = useRefreshAdmin();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      adminApi.updateSetting(key, value),
    onSuccess: refresh,
    retry: false,
  });
}

export function useBroadcasts() {
  return useInfiniteQuery({
    queryKey: qk.admin.broadcasts,
    queryFn: ({ pageParam }) => adminApi.broadcasts(pageParam as number),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });
}

export function useSendBroadcast() {
  const refresh = useRefreshAdmin();
  return useMutation({
    mutationFn: (payload: NewBroadcast) => adminApi.sendBroadcast(payload),
    onSuccess: refresh,
    retry: false,
  });
}
