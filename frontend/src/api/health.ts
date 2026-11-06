import { apiRequest } from './client';

export interface SubsystemReadiness {
  persistence: 'configured' | 'unconfigured';
  model_provider: string;
  remote_model_enabled: boolean;
}

export interface HealthResponse {
  status: 'ok';
  service: string;
  version: string;
  environment: 'development' | 'testing' | 'production';
  stage: string;
  timestamp: string;
  request_id: string;
  subsystems: SubsystemReadiness;
}

export async function fetchBackendHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/v1/health', {
    method: 'GET',
  });
}
