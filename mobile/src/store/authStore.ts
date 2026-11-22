/**
 * Authentication state.
 *
 * WHAT LIVES HERE vs IN REACT QUERY
 * ---------------------------------
 * zustand holds CLIENT state: who is signed in, and whether we have finished
 * checking. React Query holds SERVER state: photographers, bookings, reviews.
 *
 * Mixing them is the most common architectural mistake in React Native apps —
 * you end up hand-writing cache invalidation that React Query already does,
 * and stale data leaks across screens.
 *
 * The access token is deliberately NOT stored here. It lives in SecureStore
 * (Keychain / Keystore) and is read by the axios interceptor. Keeping it out
 * of a JS-visible store means a compromised third-party dependency cannot
 * simply read it off the store.
 */

import { create } from 'zustand';

import { api, tokenStorage, unwrap } from '../api/client';
import { ENDPOINTS } from '../api/config';
import type { AuthResponse, User, UserRole } from '../types/models';

interface AuthState {
  user: User | null;
  /** True until the initial "am I already signed in?" check completes. */
  isBootstrapping: boolean;
  isAuthenticated: boolean;
  /** Email of an account just created here that has not signed in yet. */
  newAccountEmail: string | null;
  /**
   * True from the first sign-in after sign-up until the code is entered or the
   * user chooses "later".
   */
  isVerifyPending: boolean;

  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<User>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: (allDevices?: boolean) => Promise<void>;
  setUser: (user: User) => void;
  finishVerify: () => void;
  clearSession: () => void;
}

export interface RegisterPayload {
  email: string;
  full_name: string;
  password: string;
  password_confirm: string;
  phone?: string;
  city?: string;
  role: Extract<UserRole, 'BUYER' | 'PHOTOGRAPHER'>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isBootstrapping: true,
  isAuthenticated: false,
  newAccountEmail: null,
  isVerifyPending: false,

  /**
   * Runs once at app start.
   *
   * A stored refresh token is not proof of a valid session — the account may
   * have been blocked, or the password changed on another device, both of
   * which bump token_version server-side. So we always verify with /auth/me/
   * rather than trusting local storage.
   */
  bootstrap: async () => {
    try {
      const refresh = await tokenStorage.getRefresh();
      if (!refresh) {
        set({ isBootstrapping: false, isAuthenticated: false, user: null });
        return;
      }
      const user = await unwrap<User>(api.get(ENDPOINTS.auth.me));
      set({ user, isAuthenticated: true, isBootstrapping: false });
    } catch {
      // Any failure means the session is unusable. Clear it and show login.
      await tokenStorage.clear();
      set({ user: null, isAuthenticated: false, isBootstrapping: false });
    }
  },

  login: async (email, password) => {
    const normalizedEmail = email.trim().toLowerCase();
    const result = await unwrap<AuthResponse>(
      api.post(ENDPOINTS.auth.login, { email: normalizedEmail, password }),
    );
    await tokenStorage.set(result.tokens.access, result.tokens.refresh);
    set({
      user: result.user,
      isAuthenticated: true,
      isVerifyPending: get().newAccountEmail === normalizedEmail,
      newAccountEmail: null,
    });
    return result.user;
  },

  /**
   * Creates the account only. The tokens in the response are deliberately not
   * kept: a new user signs in on the login screen.
   */
  register: async (payload) => {
    const email = payload.email.trim().toLowerCase();
    await unwrap<AuthResponse>(
      api.post(ENDPOINTS.auth.register, { ...payload, email }),
    );
    set({ newAccountEmail: email });
  },

  logout: async (allDevices = false) => {
    try {
      const refresh = await tokenStorage.getRefresh();
      if (refresh) {
        await api.post(ENDPOINTS.auth.logout, { refresh, all_devices: allDevices });
      }
    } catch {
      // A failed logout call must never trap the user in a signed-in state.
      // The local session is cleared regardless.
    } finally {
      await tokenStorage.clear();
      set({ user: null, isAuthenticated: false, isVerifyPending: false });
    }
  },

  setUser: (user) => set({ user }),
  finishVerify: () => set({ isVerifyPending: false }),

  /** Called by the axios interceptor when a refresh fails. */
  clearSession: () =>
    set({ user: null, isAuthenticated: false, isVerifyPending: false }),
}));

// ─── Selectors (subscribe to one slice, avoid needless re-renders) ──────────
export const useCurrentUser = () => useAuthStore((s) => s.user);
export const useIsAuthenticated = () => useAuthStore((s) => s.isAuthenticated);
export const useIsPhotographer = () =>
  useAuthStore((s) => s.user?.role === 'PHOTOGRAPHER');
export const useIsBuyer = () => useAuthStore((s) => s.user?.role === 'BUYER');
