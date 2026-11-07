import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiResource, type AsyncResourceState, type ResourceLoader } from '../api/client';

/** React adapter for the shared API resource state; it does not implement transport. */
export function useApiResource<T>(loader: ResourceLoader<T>): {
  state: AsyncResourceState<T>;
  retry: () => Promise<void>;
} {
  const resource = useMemo(() => new ApiResource(loader), [loader]);
  const [state, setState] = useState<AsyncResourceState<T>>(resource.state);

  useEffect(() => {
    const unsubscribe = resource.subscribe(setState);
    void resource.load().catch(() => undefined);
    return () => {
      unsubscribe();
      resource.reset();
    };
  }, [resource]);

  const retry = useCallback(async () => {
    await resource.retry().then(() => undefined).catch(() => undefined);
  }, [resource]);

  return { state, retry };
}
