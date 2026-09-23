import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import type { ApiErrorBody, TokenOut } from './types'

const API_PREFIX = '/api/v1'

const TOKEN_KEY = 'cdc_access_token'
const REFRESH_KEY = 'cdc_refresh_token'

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function setTokens(t: TokenOut): void {
  localStorage.setItem(TOKEN_KEY, t.access_token)
  localStorage.setItem(REFRESH_KEY, t.refresh_token)
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

const client = axios.create({
  baseURL: API_PREFIX,
  timeout: 30000,
})

client.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshing: Promise<string | null> | null = null

async function doRefresh(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  try {
    const res = await axios.post<TokenOut>(`${API_PREFIX}/auth/refresh`, {
      refresh_token: refreshToken,
    })
    setTokens(res.data)
    return res.data.access_token
  } catch {
    clearTokens()
    return null
  }
}

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const original = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined
    if (error.response?.status === 401 && original && !original._retry) {
      if (!refreshing) {
        refreshing = doRefresh().finally(() => {
          refreshing = null
        })
      }
      const token = await refreshing
      if (token) {
        original._retry = true
        original.headers = { ...original.headers, Authorization: `Bearer ${token}` }
        return client(original)
      }
    }
    return Promise.reject(error)
  },
)

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body = error.response?.data
    if (body && typeof body === 'object' && 'message' in body) {
      return String(body.message)
    }
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as Record<string, unknown>).detail
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as Record<string, unknown>
        return String(first.msg ?? '请求参数错误')
      }
    }
    return error.message || '网络请求失败'
  }
  return '未知错误'
}

export default client