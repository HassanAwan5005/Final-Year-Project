/**
 * Photographer discovery API.
 *
 * Every function returns plain data. React Query owns caching, retries and
 * background refetching — see hooks/usePhotographers.ts. Keeping the two
 * separate means these functions stay trivially testable.
 */

import { api, unwrap, unwrapFull, type ApiEnvelope } from '../client';
import { ENDPOINTS } from '../config';
import type {
  Category,
  PhotographerDetail,
  PhotographerSummary,
  Recommendation,
} from '../../types/models';

export interface PhotographerFilters {
  q?: string;
  category?: string;
  city?: string;
  min_price?: number;
  max_price?: number;
  min_rating?: number;
  min_experience?: number;
  available?: boolean;
  verified?: boolean;
  available_on?: string;
  ordering?: string;
  lat?: number;
  lng?: number;
  radius_km?: number;
  page?: number;
  page_size?: number;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  totalPages: number;
  totalItems: number;
  hasNext: boolean;
}

/** Strip undefined/empty values so they never reach the querystring. */
function clean(filters: PhotographerFilters): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === '') continue;
    out[key] = String(value);
  }
  return out;
}

export const photographersApi = {
  async list(filters: PhotographerFilters = {}): Promise<Paginated<PhotographerSummary>> {
    const envelope = await unwrapFull<PhotographerSummary[]>(
      api.get(ENDPOINTS.photographers.list, { params: clean(filters) }),
    );
    const pagination = envelope.meta?.pagination;
    return {
      items: envelope.data,
      page: pagination?.page ?? 1,
      totalPages: pagination?.total_pages ?? 1,
      totalItems: pagination?.total_items ?? envelope.data.length,
      hasNext: pagination?.has_next ?? false,
    };
  },

  detail(id: number | string) {
    return unwrap<PhotographerDetail>(api.get(ENDPOINTS.photographers.detail(id)));
  },

  trending(city?: string) {
    return unwrap<PhotographerSummary[]>(
      api.get(`${ENDPOINTS.photographers.list}trending/`, {
        params: city ? { city } : undefined,
      }),
    );
  },

  /** Real cities and the true price range, for the filter sheet. */
  filterOptions() {
    return unwrap<{
      categories: { slug: string; name: string; count: number }[];
      cities: { name: string; count: number }[];
      price_range: { min: number; max: number };
      sort_options: { value: string; label: string }[];
    }>(api.get(`${ENDPOINTS.photographers.list}filters/`));
  },

  /**
   * Image-to-Photographer Search ("Find Similar Style").
   * Uploads reference photo and returns photographers ranked by aesthetic cosine similarity.
   */
  async visualSearch(
    imageUri: string,
    params: { category?: string; city?: string; min_price?: number; max_price?: number; limit?: number } = {},
  ): Promise<{
    items: Recommendation[];
    referenceStyle: string;
    totalMatches: number;
  }> {
    const formData = new FormData();
    const filename = imageUri.split('/').pop() || 'reference.jpg';
    const match = /\.(\w+)$/.exec(filename);
    const type = match ? `image/${match[1]}` : 'image/jpeg';

    formData.append('image', {
      uri: imageUri,
      name: filename,
      type,
    } as any);

    if (params.category) formData.append('category', params.category);
    if (params.city) formData.append('city', params.city);
    if (params.min_price) formData.append('min_price', String(params.min_price));
    if (params.max_price) formData.append('max_price', String(params.max_price));
    if (params.limit) formData.append('limit', String(params.limit));

    const response = await api.post<ApiEnvelope<Recommendation[]> & { meta?: { reference_style?: string; total_matches?: number } }>(
      ENDPOINTS.photographers.visualSearch,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );

    return {
      items: response.data.data,
      referenceStyle: response.data.meta?.reference_style || 'General',
      totalMatches: response.data.meta?.total_matches || response.data.data.length,
    };
  },

  /**
   * Conversational Shoot Matchmaker:
   * Parses natural language buyer prompt (e.g. "Looking for a candid photographer in Lahore for a Mehndi event under Rs 40,000 who delivers within a week")
   * and returns structured filters with ranked tailored recommendations.
   */
  async matchmaker(
    prompt: string,
    filters?: { city?: string; category?: string; max_price?: number; delivery_days?: number; style?: string },
    limit = 20,
  ): Promise<{
    assistantMessage: string;
    parsedFilters: Record<string, unknown>;
    suggestedChips: { key: string; label: string; value: unknown }[];
    relaxedNotice?: string | null;
    photographers: Recommendation[];
    totalMatches: number;
  }> {
    const response = await api.post<
      ApiEnvelope<{
        assistant_message: string;
        parsed_filters: Record<string, unknown>;
        suggested_chips: { key: string; label: string; value: unknown }[];
        relaxed_notice?: string | null;
        photographers: Recommendation[];
      }> & { meta?: { total_matches?: number; confidence?: number } }
    >(ENDPOINTS.photographers.matchmaker, { prompt, filters, limit });

    const payload = response.data.data;
    return {
      assistantMessage: payload.assistant_message,
      parsedFilters: payload.parsed_filters,
      suggestedChips: payload.suggested_chips,
      relaxedNotice: payload.relaxed_notice,
      photographers: payload.photographers,
      totalMatches: response.data.meta?.total_matches ?? payload.photographers.length,
    };
  },
};

export const catalogApi = {
  categories() {
    return unwrap<Category[]>(api.get(ENDPOINTS.catalog.categories));
  },
};

export interface RecommendationResult {
  items: Recommendation[];
  strategy: string;
  personalised: boolean;
  modelMode: string;
  /** Non-null when the filters matched nobody and were widened. */
  relaxed: string | null;
}

export const recommendationsApi = {
  async get(params: {
    category?: string;
    city?: string;
    max_price?: number;
    limit?: number;
  } = {}): Promise<RecommendationResult> {
    const response = await api.get<
      ApiEnvelope<Recommendation[]> & {
        meta?: {
          strategy?: string;
          personalised?: boolean;
          model_mode?: string;
          relaxed?: string | null;
        };
      }
    >(ENDPOINTS.recommendations, { params: clean(params as PhotographerFilters) });

    const envelope = response.data;
    return {
      items: envelope.data,
      strategy: envelope.meta?.strategy ?? 'POPULARITY',
      personalised: envelope.meta?.personalised ?? false,
      modelMode: envelope.meta?.model_mode ?? 'none',
      relaxed: envelope.meta?.relaxed ?? null,
    };
  },

  /**
   * Report that a recommendation was tapped.
   *
   * Fire-and-forget: this is analytics, and a failure here must never block
   * the navigation the user actually asked for.
   */
  click(photographerId: number) {
    return api
      .post(`${ENDPOINTS.recommendations}click/`, { photographer_id: photographerId })
      .catch(() => undefined);
  },

};
