/**
 * API client configuration using Axios
 * API客户端配置
 */
import axios, { AxiosInstance, AxiosError, AxiosResponse } from 'axios';

/**
 * Generic API response wrapper
 * API响应包装器
 */
export interface ApiResponse<T> {
  /** Response code (响应代码) */
  code: number;
  /** Response data (响应数据) */
  data: T;
  /** Response message (响应消息) */
  message: string;
}

/**
 * Error codes mapping
 * 错误代码映射
 */
export const ERROR_CODES = {
  SUCCESS: 200,
  BAD_REQUEST: 400,
  NOT_FOUND: 404,
  BUSINESS_ERROR: 422,
  SERVER_ERROR: 500,
};

/**
 * Axios instance configuration
 * Axios实例配置
 */
const apiClient: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Request interceptor
 * 请求拦截器
 */
apiClient.interceptors.request.use(
  (config) => {
    // Add request timestamp for debugging
    console.log(`[API Request] ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error: AxiosError) => {
    console.error('[API Request Error]', error.message);
    return Promise.reject(error);
  }
);

/**
 * Response interceptor
 * 响应拦截器
 */
apiClient.interceptors.response.use(
  (response: AxiosResponse<ApiResponse<unknown>>) => {
    const { data, status } = response;
    console.log(`[API Response] ${status}`, data);
    
    // Check if API response code indicates success
    if (data.code !== ERROR_CODES.SUCCESS) {
      // Convert successful HTTP status but failed API code to error
      const error = new Error(data.message || 'API返回错误');
      (error as unknown as Record<string, unknown>).code = data.code;
      (error as unknown as Record<string, unknown>).data = data.data;
      return Promise.reject(error);
    }
    
    return response;
  },
  (error: AxiosError<ApiResponse<unknown>>) => {
    // Handle HTTP errors
    if (error.response) {
      const { status, data } = error.response;
      console.error(`[API Response Error] ${status}`, data);
      
      const errorMessage = data?.message || error.message || '服务器错误';
      const apiError = new Error(errorMessage);
      (apiError as unknown as Record<string, unknown>).code = data?.code || status;
      (apiError as unknown as Record<string, unknown>).data = data?.data;
      return Promise.reject(apiError);
    }
    
    // Network error
    console.error('[API Network Error]', error.message);
    return Promise.reject(new Error('网络连接失败，请检查服务器是否运行'));
  }
);

/**
 * Helper function to make API requests
 * API请求辅助函数
 */
export async function apiRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  url: string,
  data?: unknown
): Promise<T> {
  const response = await apiClient.request<ApiResponse<T>>({
    method,
    url,
    data,
  });
  return response.data.data;
}

/**
 * GET request helper
 * GET请求辅助函数
 */
export async function apiGet<T>(url: string): Promise<T> {
  return apiRequest<T>('GET', url);
}

/**
 * POST request helper
 * POST请求辅助函数
 */
export async function apiPost<T>(url: string, data: unknown): Promise<T> {
  return apiRequest<T>('POST', url, data);
}

/**
 * Export the configured axios instance
 * 导出配置好的axios实例
 */
export default apiClient;