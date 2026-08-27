import { defineStore } from 'pinia'
import { api } from '@/api'
import type {
  SessionSummary,
  SessionConfig,
  ChatMessage,
  GridOption,
  QuickQuestion,
  ToolRun,
  SseEventType,
} from '@/types'
import { ElMessage } from 'element-plus'

interface SessionState {
  options: {
    grids: GridOption[]
    quick_questions: QuickQuestion[]
    default_config: SessionConfig
    llm_available: boolean
  } | null
  sessions: SessionSummary[]
  currentSessionId: string | null
  // 每个会话的消息缓存（避免反复请求）
  messageMap: Record<string, ChatMessage[]>
  loading: boolean
  isStreaming: boolean
  // 当前会话正在运行中的工具（用于气泡里实时显示"正在做xx"）
  liveToolRuns: Record<string, ToolRun>
}

export const useSessionStore = defineStore('session', {
  state: (): SessionState => ({
    options: null,
    sessions: [],
    currentSessionId: null,
    messageMap: {},
    loading: false,
    isStreaming: false,
    liveToolRuns: {},
  }),

  getters: {
    currentSession(state): SessionSummary | undefined {
      return state.sessions.find((s) => s.id === state.currentSessionId)
    },
    currentMessages(state): ChatMessage[] {
      if (!state.currentSessionId) return []
      return state.messageMap[state.currentSessionId] || []
    },
    currentConfig(state): Partial<SessionConfig> {
      const s = state.sessions.find((x) => x.id === state.currentSessionId)
      return s?.config ?? {}
    },
  },

  actions: {
    // 1. 应用启动时拉一次全局选项
    async loadOptions() {
      if (this.options) return
      this.options = (await api.getOptions()) as any
    },

    // 2. 拉取会话列表（侧边栏）
    async loadSessions() {
      this.sessions = (await api.listSessions()) as any
      // 如果还没选当前会话，默认选第一个
      if (!this.currentSessionId && this.sessions.length > 0) {
        this.currentSessionId = this.sessions[0].id
        await this.loadSessionMessages(this.currentSessionId)
      }
    },

    // 3. 打开一个会话：切换当前 + 拉取该会话的历史消息（如果本地没有）
    async selectSession(id: string) {
      this.currentSessionId = id
      if (!this.messageMap[id] || this.messageMap[id].length === 0) {
        await this.loadSessionMessages(id)
      }
    },

    // 4. 拉取某会话的完整消息（页面刷新、首次进入用）
    async loadSessionMessages(id: string) {
      try {
        const data = (await api.getSession(id)) as any
        // 兼容后端字段，messages 直接用
        this.messageMap[id] = (data?.messages ?? []) as ChatMessage[]
        // 顺便同步一下会话元数据（名称等）
        if (data) {
          const idx = this.sessions.findIndex((s) => s.id === id)
          if (idx >= 0) {
            this.sessions[idx] = { ...this.sessions[idx], ...data }
          }
        }
      } catch (e) {
        this.messageMap[id] = []
      }
    },

    // 5. 新建会话（自动切过去）
    async createSession(name = '新会话', config?: SessionConfig) {
      const payload = { name }
      if (config) payload['config'] = config
      const newOne = (await api.createSession(payload)) as any
      // 列表头部插入
      this.sessions.unshift(newOne)
      this.messageMap[newOne.id] = []
      this.currentSessionId = newOne.id
      ElMessage.success('会话已创建')
      return newOne
    },

    // 6. 删除会话
    async deleteSession(id: string) {
      await api.deleteSession(id)
      this.sessions = this.sessions.filter((s) => s.id !== id)
      delete this.messageMap[id]
      if (this.currentSessionId === id) {
        this.currentSessionId = this.sessions[0]?.id ?? null
        if (this.currentSessionId) {
          await this.loadSessionMessages(this.currentSessionId)
        }
      }
      ElMessage.success('已删除')
    },

    // 7. 修改会话名称或配置
    async updateSession(id: string, patch: { name?: string; config?: SessionConfig }) {
      await api.updateSession(id, patch)
      // 更新本地缓存
      const idx = this.sessions.findIndex((s) => s.id === id)
      if (idx >= 0) {
        if (patch.name) this.sessions[idx].name = patch.name
        if (patch.config) this.sessions[idx].config = patch.config
      }
    },

    // 8. 给某个会话追加一条消息（本地立刻显示，再等后端慢慢处理）
    appendMessage(sessionId: string, msg: ChatMessage) {
      if (!this.messageMap[sessionId]) this.messageMap[sessionId] = []
      this.messageMap[sessionId].push(msg)
    },

    // 9. 获取最后一条 assistant 消息（用于打字机追加 token）
    getLastAssistantMessage(sessionId: string): ChatMessage | null {
      const list = this.messageMap[sessionId] || []
      for (let i = list.length - 1; i >= 0; i--) {
        if (list[i].role === 'assistant') return list[i]
      }
      return null
    },

    // ========================================================
    // 10. 核心：发送问题 + SSE 流式处理
    // ========================================================
    async sendQuestion(sessionId: string, question: string) {
      if (!question.trim() || this.isStreaming) return
      // 前端先把用户消息塞进去
      this.appendMessage(sessionId, {
        role: 'user',
        content: question.trim(),
      })
      // 再占个 assistant 位（后面慢慢往里面填 token）
      this.appendMessage(sessionId, {
        role: 'assistant',
        content: '',
        pending_tokens: '',
        tool_runs: [],
      })

      this.isStreaming = true
      this.liveToolRuns = {}

      try {
        await this._streamChat(sessionId, question)
        // 聊天结束：刷新下会话列表（更新 last_message / message_count）
        await this.loadSessions()
      } catch (e: any) {
        const msg = this.getLastAssistantMessage(sessionId)
        if (msg) {
          msg.content =
            (msg.pending_tokens || msg.content) +
            `\n\n❌ 出错了：${e?.message || String(e)}`
        }
        ElMessage.error('聊天失败')
      } finally {
        this.isStreaming = false
        this.liveToolRuns = {}
      }
    },

    // —— 内部：SSE 流式请求处理 ——
    // 注意：不要把 messageMap 里的消息对象引用缓存到局部变量里长期持有，
    // 每个事件到来时都通过 getLastAssistantMessage 重新取一次，
    // 保证拿到的永远是 store 里的响应式对象，直接改属性即可触发视图更新。
    async _streamChat(sessionId: string, question: string) {
      // 注意：浏览器原生 EventSource 只能 GET 不能 POST 带 body，
      // 所以用 fetch + ReadableStream 手动解析 SSE 格式。
      const resp = await fetch(`/api/sessions/${sessionId}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ question }),
      })

      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status} ${resp.statusText}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE 以 \n\n 分割事件，循环切分（sse_starlette 可能用 \r\n\r\n，一并兼容）
        let boundary: number
        while ((boundary = buffer.indexOf('\n\n')) >= 0 || (boundary = buffer.indexOf('\r\n\r\n')) >= 0) {
          const sepLen = buffer.startsWith('\r\n\r\n', boundary) ? 4 : 2
          const rawEvent = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + sepLen)
          this._handleRawSseEvent(sessionId, rawEvent)
        }
      }

      // 处理剩余尾巴
      if (buffer.trim()) {
        this._handleRawSseEvent(sessionId, buffer)
      }
    },

    // —— 内部：解析单个 SSE 事件并更新 UI 状态 ——
    _handleRawSseEvent(sessionId: string, rawEvent: string) {
      // 后端事件里带 session_id 就优先用它的（避免流式过程中用户切了会话）
      // SSE 每一行一般是 "event: xxx\ndata: {...}"
      const lines = rawEvent.split(/\r?\n/)
      let evType: SseEventType = 'token'
      let dataStr = ''
      for (const l of lines) {
        if (l.startsWith('event:')) {
          evType = l.slice(6).trim() as SseEventType
        } else if (l.startsWith('data:')) {
          dataStr += l.slice(5).trimStart()
        }
      }
      if (!dataStr) return
      let payload: any
      try {
        payload = JSON.parse(dataStr)
      } catch {
        return
      }
      // 如果后端包装过一层 {event, data} 就拆开
      if (payload && typeof payload === 'object' && 'event' in payload) {
        evType = payload.event as SseEventType
        dataStr = JSON.stringify(payload.data)
        try {
          payload = JSON.parse(dataStr)
        } catch {
          payload = payload.data
        }
      }

      // 每个事件都实时取 store 里的响应式消息对象（不长期持有旧引用）
      const assistantMsg = this.getLastAssistantMessage(sessionId)
      if (!assistantMsg) return

      // ---------- 分类型处理 ----------
      // Pinia state 是深度响应式的，直接修改属性即可触发视图更新，
      // 不需要（也不能）整体替换消息数组 —— 那样会让外部持有的引用失效。
      switch (evType) {
        case 'welcome':
          // 准备中，不用动
          break
        case 'tool_start': {
          const name = payload?.name || '工具'
          if (!assistantMsg.tool_runs) assistantMsg.tool_runs = []
          const tr: ToolRun = {
            name,
            input: payload?.input ?? {},
            output: null,
            status: 'running',
            start_time: Date.now(),
          }
          assistantMsg.tool_runs.push(tr)
          this.liveToolRuns[name] = tr
          break
        }
        case 'tool_end': {
          const name = payload?.name || '工具'
          const runs = assistantMsg.tool_runs || []
          for (let i = runs.length - 1; i >= 0; i--) {
            const t = runs[i]
            if (t.name === name && t.status === 'running') {
              t.status = 'ok'
              t.output = payload?.output_preview ?? t.output
              t.end_time = Date.now()
              delete this.liveToolRuns[name]
              break
            }
          }
          break
        }
        case 'token': {
          const text = payload?.text || ''
          if (text) {
            assistantMsg.pending_tokens = (assistantMsg.pending_tokens || '') + text
            assistantMsg.content = assistantMsg.pending_tokens
          }
          break
        }
        case 'done': {
          const finalText = payload?.ai_text || ''
          if (finalText) {
            assistantMsg.content = finalText
            assistantMsg.pending_tokens = finalText
          }
          if (payload?.tool_runs?.length) {
            assistantMsg.tool_runs = [...payload.tool_runs]
          }
          break
        }
        case 'error': {
          assistantMsg.content =
            (assistantMsg.pending_tokens || assistantMsg.content) +
            `\n\n❌ 处理过程中出错：${payload?.message || '未知错误'}`
          break
        }
      }
    },
  },
})