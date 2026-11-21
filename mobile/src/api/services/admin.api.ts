/**
 * Admin API — product listing moderation.
 *
 * Every endpoint here is ADMIN-only on the server; the app showing these
 * screens only to admins is a convenience, not the security boundary.
 */

import { api, unwrap, unwrapFull } from '../client';
import { ENDPOINTS } from '../config';
import type { AdminListing } from '../../types/models';

export const adminApi = {
  /** Listings published by their sellers and waiting for approval. */
  async pendingListings(): Promise<{ items: AdminListing[]; total: number }> {
    const envelope = await unwrapFull<AdminListing[]>(
      api.get(ENDPOINTS.admin.products, { params: { page_size: 100 } }),
    );
    return {
      items: envelope.data,
      total: envelope.meta?.pagination?.total_items ?? envelope.data.length,
    };
  },

  approveListing(id: number) {
    return unwrap<AdminListing>(api.post(ENDPOINTS.admin.approveProduct(id), {}));
  },

  /** Reject: the reason is sent to the seller as a notification. */
  rejectListing(id: number, reason: string) {
    return unwrap<AdminListing>(api.post(ENDPOINTS.admin.removeProduct(id), { reason }));
  },
};
