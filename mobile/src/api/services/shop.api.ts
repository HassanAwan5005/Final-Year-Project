/**
 * Shop, profile and wishlist API.
 *
 * The shop is a classifieds board: sellers post ads and buyers message them.
 * There is no cart or checkout. A file path is never sent either — product
 * bytes from past orders are fetched by redeeming a single-use ticket from
 * `requestDownload()`, never from a URL in the product payload.
 */

import { api, unwrap, unwrapFull } from '../client';
import { ENDPOINTS } from '../config';
import type {
  BuyerProfile,
  DigitalProduct,
  DigitalProductDetail,
  DownloadTicket,
  Order,
  OrderItem,
  PhotographerSelfProfile,
  SellerProduct,
  SellerProductDetail,
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

  // ─── Past orders ─────────────────────────────────────────────────────────
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

  /** One of the caller's own ads, including its photos and address. */
  sellerProduct(id: number) {
    return unwrap<SellerProductDetail>(api.get(ENDPOINTS.marketplace.sellerProduct(id)));
  },

  /** List a product for sale (buyers and photographers). Sent as multipart. */
  createListing(payload: CreateListingPayload) {
    return unwrap<SellerProduct>(
      api.post(ENDPOINTS.marketplace.sellerProducts, listingForm(payload), {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    );
  },

  /** Edit the whole ad. Photos not in `keep_photos` are removed. */
  updateListing({ id, keep_photos, ...payload }: UpdateListingPayload) {
    const form = listingForm(payload);
    keep_photos.forEach((path) => form.append('keep_photos', path));
    return unwrap<SellerProductDetail>(
      api.patch(ENDPOINTS.marketplace.sellerProduct(id), form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    );
  },

  /** Sold: the ad leaves the shop. Not sold: it goes back on sale. */
  setListingSold(id: number, sold: boolean) {
    return unwrap<SellerProduct>(
      api.post(
        sold
          ? ENDPOINTS.marketplace.sellerProductMarkSold(id)
          : ENDPOINTS.marketplace.sellerProductMarkAvailable(id),
      ),
    );
  },

  async deleteListing(id: number): Promise<void> {
    await api.delete(ENDPOINTS.marketplace.sellerProduct(id));
  },
};

function listingForm(payload: CreateListingPayload): FormData {
  const form = new FormData();
  form.append('title', payload.title);
  form.append('description', payload.description);
  form.append('price', String(payload.price));
  form.append('product_type', payload.product_type);
  form.append('address', payload.address);
  payload.photos.forEach((photo, index) => {
    // React Native's FormData wants this exact triple.
    form.append('photos', {
      uri: photo.uri,
      name: photo.name ?? `product-${index + 1}.jpg`,
      type: photo.type ?? 'image/jpeg',
    } as unknown as Blob);
  });
  return form;
}

export interface CreateListingPayload {
  title: string;
  description: string;
  price: number;
  product_type: string;
  address: string;
  photos: { uri: string; name?: string; type?: string }[];
}

export interface UpdateListingPayload extends CreateListingPayload {
  id: number;
  /** Existing photos to keep, in order; new `photos` go after them. */
  keep_photos: string[];
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
