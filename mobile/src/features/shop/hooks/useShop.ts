/**
 * React Query hooks for the shop, profile and wishlist.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { qk } from '../../../api/queryKeys';
import { useAuthStore } from '../../../store/authStore';
import {
  profileApi,
  shopApi,
  wishlistApi,
  type CreateListingPayload,
  type ShopFilters,
  type UpdateListingPayload,
} from '../../../api/services/shop.api';
import type { FlagReason } from '../../../types/models';

// ═══════════════════════════════════════════════════════════════════════════
// BROWSE
// ═══════════════════════════════════════════════════════════════════════════
export function useProducts(filters: ShopFilters = {}) {
  return useInfiniteQuery({
    queryKey: qk.shop.list(filters),
    queryFn: ({ pageParam }) => shopApi.list({ ...filters, page: pageParam as number }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.hasNext ? last.page + 1 : undefined),
    staleTime: 2 * 60_000,
  });
}

export function useProduct(slug: string | null) {
  return useQuery({
    queryKey: qk.shop.detail(slug ?? ''),
    queryFn: () => shopApi.detail(slug!),
    enabled: Boolean(slug),
    staleTime: 5 * 60_000,
  });
}

export function useShopFilterOptions() {
  return useQuery({
    queryKey: qk.shop.filterOptions,
    queryFn: () => shopApi.filterOptions(),
    staleTime: 30 * 60_000,
  });
}

export function useFeaturedProducts() {
  return useQuery({
    queryKey: qk.shop.featured,
    queryFn: () => shopApi.featured(),
    staleTime: 10 * 60_000,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// PAST PURCHASES
// ═══════════════════════════════════════════════════════════════════════════
export function usePurchases() {
  return useQuery({
    queryKey: qk.shop.purchases,
    queryFn: () => shopApi.purchases(),
    staleTime: 60_000,
  });
}

export function useOrders() {
  return useQuery({
    queryKey: qk.shop.orders,
    queryFn: () => shopApi.orders(),
    staleTime: 60_000,
  });
}

export function useRequestDownload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, fileId }: { itemId: number; fileId?: number }) =>
      shopApi.requestDownload(itemId, fileId),
    // Each ticket consumes one of the buyer's downloads, so the remaining
    // count on the library screen has changed.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.shop.purchases }),
    retry: false,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// SELLER
// ═══════════════════════════════════════════════════════════════════════════
export function useSellerProducts() {
  return useQuery({
    queryKey: qk.shop.sellerProducts,
    queryFn: () => shopApi.sellerProducts(),
    staleTime: 60_000,
  });
}

export function useSellerSummary() {
  return useQuery({
    queryKey: qk.shop.sellerSummary,
    queryFn: () => shopApi.sellerSummary(),
    staleTime: 60_000,
  });
}

/** Always refetched on open: the edit form must start from the latest ad. */
export function useSellerProduct(id: number) {
  return useQuery({
    queryKey: qk.shop.sellerProduct(id),
    queryFn: () => shopApi.sellerProduct(id),
    staleTime: 0,
  });
}

export function useUpdateListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateListingPayload) => shopApi.updateListing(payload),
    onSuccess: () => {
      // The ad shows in the grid, its own page, My listings, Saved and chats.
      queryClient.invalidateQueries({ queryKey: qk.shop.all });
      queryClient.invalidateQueries({ queryKey: qk.wishlist });
      queryClient.invalidateQueries({ queryKey: qk.chat.all });
    },
    // A retry would upload the new photos twice.
    retry: false,
  });
}

/** The ad shows in the grid, its own page, My listings, Saved and chats. */
function useRefreshAfterListingChange() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: qk.shop.all });
    queryClient.invalidateQueries({ queryKey: qk.wishlist });
    queryClient.invalidateQueries({ queryKey: qk.chat.all });
  };
}

export function useSetListingSold() {
  const refresh = useRefreshAfterListingChange();
  return useMutation({
    mutationFn: ({ id, sold }: { id: number; sold: boolean }) =>
      shopApi.setListingSold(id, sold),
    onSuccess: refresh,
  });
}

export function useReportProduct() {
  return useMutation({
    mutationFn: ({ slug, reason }: { slug: string; reason: FlagReason }) =>
      shopApi.reportProduct(slug, reason),
    retry: false,
  });
}

export function useDeleteListing() {
  const refresh = useRefreshAfterListingChange();
  return useMutation({
    mutationFn: (id: number) => shopApi.deleteListing(id),
    onSuccess: refresh,
    retry: false,
  });
}

export function useCreateListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateListingPayload) => shopApi.createListing(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.shop.sellerProducts });
      queryClient.invalidateQueries({ queryKey: qk.shop.sellerSummary });
    },
    // Not idempotent: a retry would create a second listing.
    retry: false,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// PROFILE
// ═══════════════════════════════════════════════════════════════════════════
export function useMyProfile() {
  return useQuery({
    queryKey: qk.profile.me,
    queryFn: () => profileApi.me(),
    staleTime: 60_000,
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => profileApi.update(payload),
    onSuccess: (profile) => {
      queryClient.setQueryData(qk.profile.me, profile);
      // A photographer pausing bookings changes their public card too.
      queryClient.invalidateQueries({ queryKey: qk.photographers.all });
    },
    retry: false,
  });
}

export function useUpdateUser() {
  const setUser = useAuthStore((s) => s.setUser);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { full_name?: string; phone?: string; city?: string; delete_avatar?: boolean }) =>
      profileApi.updateUser(payload),
    onSuccess: (updatedUser) => {
      setUser(updatedUser);
      queryClient.invalidateQueries({ queryKey: qk.profile.me });
      queryClient.invalidateQueries({ queryKey: qk.photographers.all });
    },
    retry: false,
  });
}

export function useDeleteAccount() {
  const logout = useAuthStore((s) => s.logout);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reason?: string) => profileApi.deleteAccount(reason),
    onSuccess: async () => {
      queryClient.clear();
      await logout();
    },
    retry: false,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// WISHLIST
// ═══════════════════════════════════════════════════════════════════════════
export function useWishlist() {
  return useQuery({
    queryKey: qk.wishlist,
    queryFn: () => wishlistApi.list(),
    staleTime: 30_000,
  });
}

export function useToggleWishlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (target: { photographer?: number; product?: number }) =>
      wishlistApi.toggle(target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.wishlist });
      // The heart on every card that shows this target is now stale.
      queryClient.invalidateQueries({ queryKey: qk.shop.all });
      queryClient.invalidateQueries({ queryKey: qk.photographers.all });
    },
    retry: false,
  });
}
