import axios, { AxiosInstance, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types'

const request: AxiosInstance = axios.create({
  baseURL: '/',   // vite 的 proxy 已经把 /api 转到 8000 了，这里根路径就行
  timeout: 120000, // 电网计算比较慢，给2分钟
  headers: {
    'Content-Type': 'application/json',
  },
})

// 响应拦截：统一解包 {code,message,data}
request.interceptors.response.use(
  (res: AxiosResponse<ApiResponse>) => {
    const payload = res.data
    // 非标准返回（比如 /docs 这种直接 HTML 的）直接放行
    if (!payload || typeof payload !== 'object' || !('code' in payload)) {
      return res
    }
    if (payload.code === 0) {
      // 把 data 解出来，这样业务代码 await api.xxx() 就直接拿到 data
      return payload.data as unknown as AxiosResponse<any>
    }
    ElMessage.error(payload.message || '请求失败')
    return Promise.reject(new Error(payload.message || 'Request failed'))
  },
  (err) => {
    const msg =
      err?.response?.data?.message ||
      err?.message ||
      '网络异常，请检查后端是否启动'
    ElMessage.error(msg)
    return Promise.reject(err)
  },
)

// ============ 下面是业务接口（对应 main.py 的路由） ============

export const api = {
  // 健康检查
  health: () => request.get<any, any>('/api/health'),

  // 前端启动选项（电网下拉、快捷问题、默认配置）
  getOptions: () => request.get<any, {
    grids: any[]
    quick_questions: any[]
    default_config: any
    llm_available: boolean
  }>('/api/config/options'),

  // 会话 CRUD
  createSession: (data: { name?: string; config?: any }) =>
    request.post<any, any>('/api/sessions', data),
  listSessions: (limit = 100) =>
    request.get<any, any[]>('/api/sessions', { params: { limit } }),
  getSession: (id: string) =>
    request.get<any, any>('/api/sessions/' + id),
  updateSession: (id: string, data: { name?: string; config?: any }) =>
    request.patch<any, any>('/api/sessions/' + id, data),
  deleteSession: (id: string) =>
    request.delete<any, any>('/api/sessions/' + id),
  resetSessionGrid: (id: string) =>
    request.post<any, any>(`/api/sessions/${id}/reset`),

  // 聊天接口（SSE 流式）直接自己调用 fetch，不走 axios
}

export default request