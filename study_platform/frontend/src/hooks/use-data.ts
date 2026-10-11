import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
export function useAction() {
  const client = useQueryClient();
  return useMutation({ mutationFn: async (task: () => Promise<unknown>) => task(), onSuccess: async () => { await client.invalidateQueries(); }, onError: (error: Error) => toast.error(error.message) });
}
