import { apiRequest } from './client';
import type { HealthResponse } from './types';

export type { HealthResponse, SubsystemReadiness } from './types';

export async function fetchBackendHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/v1/health', {
    method: 'GET',
  });
}
