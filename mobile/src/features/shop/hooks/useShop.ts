/**
 * React Query hooks for the shop, profile and wishlist.
 *
 * WHAT A PURCHASE INVALIDATES
 * ---------------------------
 * Buying (cash on delivery) touches four things a user can see at once: the
 * cart (now empty), the purchases library (now larger), the orders list, and
 * the product grid (those cards are now "Owned"). Invalidating only
 * the cart leaves a Buy button on something the buyer already owns, which
 * then errors — so the mutations below clear whole key prefixes rather than
 * naming individual queries.
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
  type CheckoutDelivery,
  type CreateListingPayload,
  type ShopFilters,
} from '../../../api/services/shop.api';

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
// CART
// ═══════════════════════════════════════════════════════════════════════════
export function useCart() {
  return useQuery({
    queryKey: qk.shop.cart,
    queryFn: () => shopApi.cart(),
    staleTime: 15_000,
  });
}

function useCartMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (cart) => {
      // The response IS the new cart, so seed it rather than refetching.
      queryClient.setQueryData(qk.shop.cart, cart);
      // The grid's `in_cart` flags are now stale.
      queryClient.invalidateQueries({ queryKey: qk.shop.list({}) , exact: false });
    },
    retry: false,
  });
}

export function useAddToCart() {
  return useCartMutation((productId: number) => shopApi.addToCart(productId));
}

export function useRemoveFromCart() {
  return useCartMutation((productId: number) => shopApi.removeFromCart(productId));
}

export function useClearCart() {
  return useCartMutation(() => shopApi.clearCart());
}

// ═══════════════════════════════════════════════════════════════════════════
// PURCHASE
// ═══════════════════════════════════════════════════════════════════════════
export function useCheckout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (delivery: CheckoutDelivery) => shopApi.checkout(delivery),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.shop.all });
      queryClient.invalidateQueries({ queryKey: qk.profile.all });
    },
    // Deliberately no retry: an automatic replay of a payment is not
    // something a library should decide. The Idempotency-Key makes a
    // *user-initiated* retry safe, which is the right place for that choice.
    retry: false,
  });
}

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
