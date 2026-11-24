/**
 * Admin API — everything the admin app's screens call.
 *
 * Every endpoint here is ADMIN-only on the server; the app showing these
 * screens only to admins is a convenience, not the security boundary. Every
 * write is audited server-side and goes through the same business rules as the
 * rest of the app (e.g. force-cancel uses the booking state machine).
 */

import { api, unwrap, unwrapFull } from '../client';
import { ENDPOINTS } from '../config';
import type {
  AdminBooking,
  AdminBookingDetail,
  AdminDashboard,
  AdminUser,
  AdminUserDetail,
  AdminUserRole,
  AuditEntry,
  Broadcast,
  BroadcastAudience,
  BookingStatus,
  FlagContentType,
  FlagStatus,
  ModerationFlag,
  PlatformSetting,
} from '../../types/models';
import type { Paginated } from './photographers.api';

const PAGE_SIZE = 30;

/** Drop empty filters so the query string carries only what was chosen. */
function clean(params: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== '' && value !== null),
  );
}

async function paged<T>(url: string, params: Record<string, unknown>): Promise<Paginated<T>> {
  const envelope = await unwrapFull<T[]>(
    api.get(url, { params: clean({ page_size: PAGE_SIZE, ...params }) }),
  );
  const pagination = envelope.meta?.pagination;
  return {
    items: envelope.data,
    page: pagination?.page ?? 1,
    totalPages: pagination?.total_pages ?? 1,
    totalItems: pagination?.total_items ?? envelope.data.length,
    hasNext: pagination?.has_next ?? false,
  };
}

export interface AdminUserFilters {
  q?: string;
  role?: AdminUserRole;
  blocked?: boolean;
}

export interface AdminFlagFilters {
  status?: FlagStatus;
  content_type?: FlagContentType;
}

export interface AdminBookingFilters {
  q?: string;
  status?: BookingStatus;
}

export interface NewBroadcast {
  title: string;
  body: string;
  audience: BroadcastAudience;
  city_filter?: string;
  send_push: boolean;
}

export const adminApi = {
  // ─── Dashboard ───────────────────────────────────────────────────────────
  dashboard(days = 30) {
    return unwrap<AdminDashboard>(api.get(ENDPOINTS.admin.dashboard, { params: { days } }));
  },

  // ─── Users ───────────────────────────────────────────────────────────────
  users(filters: AdminUserFilters, page: number) {
    return paged<AdminUser>(ENDPOINTS.admin.users, {
      q: filters.q?.trim(),
      role: filters.role,
      blocked: filters.blocked === undefined ? undefined : String(filters.blocked),
      page,
    });
  },

  user(id: number) {
    return unwrap<AdminUserDetail>(api.get(ENDPOINTS.admin.user(id)));
  },

  /** Revokes the user's sessions and cancels their open bookings. */
  blockUser(id: number, reason: string) {
    return unwrap<AdminUserDetail>(api.post(ENDPOINTS.admin.blockUser(id), { reason }));
  },

  unblockUser(id: number, reason = '') {
    return unwrap<AdminUserDetail>(api.post(ENDPOINTS.admin.unblockUser(id), { reason }));
  },

  // ─── Reports & flags ─────────────────────────────────────────────────────
  flags(filters: AdminFlagFilters, page: number) {
    return paged<ModerationFlag>(ENDPOINTS.admin.flags, { ...filters, page });
  },

  claimFlag(id: number) {
    return unwrap<ModerationFlag>(api.post(ENDPOINTS.admin.claimFlag(id), {}));
  },

  /** ACTIONED also takes the content down (hides the review, removes the ad…). */
  resolveFlag(id: number, action: 'ACTIONED' | 'DISMISSED', note: string) {
    return unwrap<ModerationFlag>(
      api.post(ENDPOINTS.admin.resolveFlag(id), { action, note }),
    );
  },

  // ─── Bookings ────────────────────────────────────────────────────────────
  bookings(filters: AdminBookingFilters, page: number) {
    return paged<AdminBooking>(ENDPOINTS.admin.bookings, {
      q: filters.q?.trim(),
      status: filters.status,
      page,
    });
  },

  booking(id: number) {
    return unwrap<AdminBookingDetail>(api.get(ENDPOINTS.admin.booking(id)));
  },

  /** Cancels through the booking state machine; both parties are notified. */
  forceCancelBooking(id: number, reason: string) {
    return unwrap<{ id: number; status: string }>(
      api.post(ENDPOINTS.admin.forceCancelBooking(id), { reason }),
    );
  },

  // ─── Audit log · settings · broadcasts ───────────────────────────────────
  audit(filters: { action?: string }, page: number) {
    return paged<AuditEntry>(ENDPOINTS.admin.audit, { ...filters, page });
  },

  settings() {
    return unwrap<PlatformSetting[]>(api.get(ENDPOINTS.admin.settings));
  },

  updateSetting(key: string, value: string) {
    return unwrap<PlatformSetting>(api.patch(ENDPOINTS.admin.setting(key), { value }));
  },

  broadcasts(page: number) {
    return paged<Broadcast>(ENDPOINTS.admin.broadcasts, { page });
  },

  sendBroadcast(payload: NewBroadcast) {
    return unwrap<Broadcast>(
      api.post(ENDPOINTS.admin.broadcasts, {
        ...payload,
        city_filter: payload.audience === 'CITY' ? payload.city_filter?.trim() : '',
        send_email: false,
      }),
    );
  },
};
