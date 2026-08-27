// 通用类型定义

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// 会话级配置
export interface SessionConfig {
  default_grid_type: string
  ui_show_tool_details: boolean
  ui_max_table_rows: number
  ui_theme: string
}

// 会话列表里的摘要项
export interface SessionSummary {
  id: string
  name: string
  last_message: string
  message_count: number
  created_at: string | null
  updated_at: string | null
  config: Partial<SessionConfig>
}

// 单条消息（用户/AI/工具）
export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string | any[]
  // assistant 可能带工具调用
  tool_calls?: Array<{
    id?: string
    name: string
    args: Record<string, any>
  }>
  // tool 消息专用
  tool_name?: string
  tool_call_id?: string
  // UI 辅助
  pending_tokens?: string  // 打字机累积中的文本
  tool_runs?: ToolRun[]    // done 事件里返回的工具调用链
}

export interface ToolRun {
  name: string
  input: Record<string, any>
  output: any
  status: 'running' | 'ok' | 'error'
  start_time?: number
  end_time?: number
}

// 前端下拉框/选项
export interface GridOption {
  value: string
  label: string
  desc: string
}
export interface QuickQuestion {
  label: string
  example: string
}

// 聊天 SSE 事件
export type SseEventType =
  | 'welcome'
  | 'tool_start'
  | 'tool_end'
  | 'token'
  | 'done'
  | 'error'

export interface SseEventData {
  event: SseEventType
  data: {
    session_id?: string
    question?: string
    name?: string
    input?: any
    output_preview?: any
    text?: string
    ai_text?: string
    tool_runs?: ToolRun[]
    message?: string
    traceback?: string
    run_id?: string
  }
}