/**
 * Shop, profile and wishlist API.
 *
 * TWO THINGS THIS FILE NEVER SENDS
 * -------------------------------
 * 1. A price. `checkout()` posts only the delivery details (cash on
 *    delivery) — the server totals the cart
 *    itself. A client that could name its own total buys a Rs 12,000 preset
 *    pack for one rupee, and no amount of later validation is as reliable as
 *    simply never reading the number.
 * 2. A file path. Product bytes are fetched by redeeming a single-use ticket
 *    from `requestDownload()`, never from a URL in the product payload.
 */

import { api, unwrap, unwrapFull } from '../client';
import { ENDPOINTS } from '../config';
import type {
  BuyerProfile,
  Cart,
  DigitalProduct,
  DigitalProductDetail,
  DownloadTicket,
  Order,
  OrderItem,
  PhotographerSelfProfile,
  SellerProduct,
  SellerSummary,
  ShopFilterOptions,
  User,
  Wishlist,
  WishlistCounts,
} from '../../types/models';

export interface ShopFilters {
  q?: string;
  product_type?: string;
  category?: string;
  license_type?: string;
  min_price?: number;
  max_price?: number;
  on_sale?: boolean;
  affordable?: boolean;
  ordering?: string;
  page?: number;
}

export interface ProductPage {
  items: DigitalProduct[];
  page: number;
  hasNext: boolean;
}

function clean(filters: object): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === '') continue;
    out[key] = String(value);
  }
  return out;
}

/** Unique per submit attempt — Hermes has no `crypto.randomUUID`. */
function idempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export const shopApi = {
  async list(filters: ShopFilters = {}): Promise<ProductPage> {
    const envelope = await unwrapFull<DigitalProduct[]>(
      api.get(ENDPOINTS.marketplace.products, { params: clean(filters) }),
    );
    return {
      items: envelope.data,
      page: envelope.meta?.pagination?.page ?? 1,
      hasNext: envelope.meta?.pagination?.has_next ?? false,
    };
  },

  detail(slug: string) {
    return unwrap<DigitalProductDetail>(api.get(ENDPOINTS.marketplace.product(slug)));
  },

  filterOptions() {
    return unwrap<ShopFilterOptions>(api.get(ENDPOINTS.marketplace.productFilters));
  },

  featured() {
    return unwrap<DigitalProduct[]>(api.get(ENDPOINTS.marketplace.featured));
  },

  bestsellers() {
    return unwrap<DigitalProduct[]>(api.get(ENDPOINTS.marketplace.bestsellers));
  },

  // ─── Cart ────────────────────────────────────────────────────────────────
  // Every mutation returns the whole cart, so the screen re-renders from one
  // authoritative payload instead of patching a local copy and hoping the two
  // agree about the total.
  cart() {
    return unwrap<Cart>(api.get(ENDPOINTS.marketplace.cart));
  },

  addToCart(productId: number) {
    return unwrap<Cart>(
      api.post(ENDPOINTS.marketplace.cartAdd, { product: productId }),
    );
  },

  removeFromCart(productId: number) {
    return unwrap<Cart>(api.post(ENDPOINTS.marketplace.cartRemove(productId), {}));
  },

  clearCart() {
    return unwrap<Cart>(api.post(ENDPOINTS.marketplace.cartClear, {}));
  },

  // ─── Orders ──────────────────────────────────────────────────────────────
  /** Cash on delivery: the delivery address and phone are required. */
  checkout(delivery: CheckoutDelivery, key = idempotencyKey('ord')) {
    return unwrap<Order>(
      api.post(
        ENDPOINTS.marketplace.checkout,
        delivery,
        { headers: { 'Idempotency-Key': key } },
      ),
    );
  },

  orders() {
    return unwrap<Order[]>(api.get(ENDPOINTS.marketplace.orders));
  },

  order(id: number) {
    return unwrap<Order>(api.get(ENDPOINTS.marketplace.order(id)));
  },

  purchases() {
    return unwrap<OrderItem[]>(api.get(ENDPOINTS.marketplace.purchases));
  },

  /**
   * Mint a single-use download link.
   *
   * The link is spent on redemption and expires in 15 minutes, so it must be
   * requested each time — caching one and reusing it returns 410.
   */
  requestDownload(itemId: number, fileId?: number) {
    return unwrap<DownloadTicket>(
      api.post(ENDPOINTS.marketplace.download(itemId), fileId ? { file: fileId } : {}),
    );
  },

  // ─── Seller ──────────────────────────────────────────────────────────────
  /** Includes unpublished drafts, so the payload carries the moderation flags. */
  sellerProducts() {
    return unwrap<SellerProduct[]>(api.get(ENDPOINTS.marketplace.sellerProducts));
  },

  sellerSummary() {
    return unwrap<SellerSummary>(api.get(ENDPOINTS.marketplace.sellerSummary));
  },

  /** List a product for sale (buyers and photographers). Sent as multipart. */
  createListing(payload: CreateListingPayload) {
    const form = new FormData();
    form.append('title', payload.title);
    form.append('description', payload.description);
    form.append('price', String(payload.price));
    form.append('product_type', payload.product_type);
    payload.photos.forEach((photo, index) => {
      // React Native's FormData wants this exact triple.
      form.append('photos', {
        uri: photo.uri,
        name: photo.name ?? `product-${index + 1}.jpg`,
        type: photo.type ?? 'image/jpeg',
      } as unknown as Blob);
    });
    return unwrap<SellerProduct>(
      api.post(ENDPOINTS.marketplace.sellerProducts, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    );
  },
};

export interface CheckoutDelivery {
  delivery_address: string;
  delivery_phone: string;
}

export interface CreateListingPayload {
  title: string;
  description: string;
  price: number;
  product_type: string;
  photos: { uri: string; name?: string; type?: string }[];
}

export const profileApi = {
  /**
   * The caller's role-specific profile.
   *
   * Account fields (name, phone, city, avatar) live at /auth/me/ and are owned
   * by the auth store — this is the buyer's preferences or the photographer's
   * public listing, and the two endpoints deliberately do not overlap.
   */
  me() {
    return unwrap<BuyerProfile | PhotographerSelfProfile>(
      api.get(ENDPOINTS.profiles.me),
    );
  },

  update(payload: Record<string, unknown>) {
    return unwrap<BuyerProfile | PhotographerSelfProfile>(
      api.patch(ENDPOINTS.profiles.update, payload),
    );
  },

  updateUser(payload: { full_name?: string; phone?: string; city?: string; delete_avatar?: boolean }) {
    return unwrap<User>(api.patch(ENDPOINTS.auth.me, payload));
  },

  deleteAccount(reason = 'User requested account deletion') {
    return api.delete(ENDPOINTS.auth.deleteAccount, { data: { reason } });
  },

};

export const wishlistApi = {
  list() {
    return unwrap<Wishlist>(api.get(ENDPOINTS.wishlist.list));
  },

  /** One endpoint for the heart icon — returns the state it left behind. */
  toggle(target: { photographer?: number; product?: number }) {
    return unwrap<{ is_saved: boolean; counts: WishlistCounts }>(
      api.post(ENDPOINTS.wishlist.toggle, target),
    );
  },

  remove(itemId: number) {
    return api.delete(ENDPOINTS.wishlist.remove(itemId));
  },
};
