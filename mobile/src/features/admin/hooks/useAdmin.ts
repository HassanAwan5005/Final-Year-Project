/** React Query hooks for the admin moderation screens. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { qk } from '../../../api/queryKeys';
import { adminApi } from '../../../api/services/admin.api';

export function usePendingListings() {
  return useQuery({
    queryKey: qk.admin.pendingListings,
    queryFn: () => adminApi.pendingListings(),
  });
}

function useAfterDecision() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: qk.admin.all });
    queryClient.invalidateQueries({ queryKey: qk.shop.all });
  };
}

export function useApproveListing() {
  const after = useAfterDecision();
  return useMutation({
    mutationFn: (id: number) => adminApi.approveListing(id),
    onSuccess: after,
    retry: false,
  });
}

export function useRejectListing() {
  const after = useAfterDecision();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      adminApi.rejectListing(id, reason),
    onSuccess: after,
    retry: false,
  });
}
