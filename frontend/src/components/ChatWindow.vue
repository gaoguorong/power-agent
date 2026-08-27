<template>
  <div class="chat-window flex-col h-full">
    <!-- ============== 欢迎页（空会话时显示） ============== -->
    <div v-if="!hasAnyMessage" class="welcome flex-col">
      <div class="hero">
        <div class="hero-icon">
          <el-icon :size="56" color="#fff"><Lightning /></el-icon>
        </div>
        <h1>⚡ 电网分析智能体</h1>
        <p class="muted" style="margin-top: 6px;">
          用自然语言对话方式进行潮流计算、N-1校核、故障分析、无功优化等电力系统分析
        </p>
      </div>

      <!-- 快捷问题芯片 -->
      <div class="quick-area">
        <h3>
          <el-icon><MagicStick /></el-icon>
          试试这些问题
        </h3>
        <div class="quick-grid">
          <el-card
            v-for="(q, i) in store.options?.quick_questions || []"
            :key="i"
            class="quick-card"
            shadow="hover"
            @click="fillInput(q.example)"
          >
            <div class="card-label">{{ q.label }}</div>
            <div class="card-example">{{ q.example }}</div>
          </el-card>
        </div>
      </div>
    </div>

    <!-- ============== 消息流 ============== -->
    <el-scrollbar
      v-else
      ref="scrollRef"
      class="messages-scroll flex-1"
      :noresize="true"
    >
      <div class="messages-inner">
        <ChatMessageItem
          v-for="(m, i) in store.currentMessages"
          :key="msgKey(m, i)"
          :message="m"
        />
        <!-- 打字机状态下的光标闪烁 -->
        <div v-if="store.isStreaming && hasLatestAssistant" class="typing-dot">
          <span /><span /><span />
        </div>
      </div>
    </el-scrollbar>

    <!-- ============== 输入区 ============== -->
    <div class="input-area">
      <!-- 快捷芯片 -->
      <div class="quick-chips" v-if="hasAnyMessage">
        <el-tag
          v-for="(q, i) in (store.options?.quick_questions || []).slice(0, 6)"
          :key="i"
          class="chip"
          effect="plain"
          type="info"
          round
          @click="fillInput(q.example)"
        >
          {{ q.label }}
        </el-tag>
      </div>

      <div class="input-box flex gap-8">
        <div class="ta-wrap flex-1 flex-col">
          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            :placeholder="placeholderText"
            :disabled="store.isStreaming"
            @keydown="onKeyDown"
            resize="none"
          />
          <div class="ta-hint muted">
            <span>Shift+Enter 换行，Enter 发送</span>
            <span>{{ inputText.length }}/5000</span>
          </div>
        </div>

        <el-button
          type="primary"
          class="send-btn"
          :icon="store.isStreaming ? Loading : Promotion"
          :disabled="!canSend"
          :loading="store.isStreaming"
          @click="doSend"
        >
          {{ store.isStreaming ? '处理中' : '发送' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  Lightning, MagicStick, Promotion, Loading,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ChatMessageItem from '@/components/ChatMessageItem.vue'
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()
const inputText = ref('')
const scrollRef = ref<any>(null)

const hasAnyMessage = computed(() => store.currentMessages.length > 0)

const hasLatestAssistant = computed(() => {
  const msgs = store.currentMessages
  if (!msgs.length) return false
  const last = msgs[msgs.length - 1]
  return last.role === 'assistant'
})

const placeholderText = computed(() => {
  if (!store.options?.llm_available) return '⚠️ 未配置LLM，可能无法正确分析问题，请检查后端配置'
  return '请输入问题，例如：基于30节点系统做潮流计算，检查过载和电压越限...'
})

const canSend = computed(
  () =>
    !!inputText.value.trim() &&
    !store.isStreaming,
)

// 监听消息变化：自动滚到底部
watch(
  () => [store.currentMessages.length, store.currentMessages.at(-1)?.content, store.isStreaming],
  async () => {
    await nextTick()
    scrollRef.value?.setScrollTop?.(9999999)
  },
  { flush: 'post' },
)

function fillInput(text: string) {
  inputText.value = text
}

function onKeyDown(e: KeyboardEvent) {
  // Enter 发（非shift），Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    doSend()
  }
}

/**
 * v-for key 生成：强制让 Vue 在内容/工具状态变更时重建该消息子组件，
 * 彻底绕开「深层属性修改不触发重渲染」的响应式问题。
 */
function msgKey(m: any, i: number) {
  const content = (typeof m?.content === 'string' ? m.content : String(m?.content ?? ''))
  const trCount = Array.isArray(m?.tool_runs) ? m.tool_runs.length : 0
  return `${i}-${m.role}-${content.length}-${trCount}-${content.slice(0, 12)}`
}

async function ensureSession() {
  if (store.currentSessionId) return store.currentSessionId
  // 先尝试选列表里的第一个
  if (store.sessions.length > 0) {
    store.currentSessionId = store.sessions[0].id
    await store.loadSessionMessages(store.currentSessionId)
    return store.currentSessionId
  }
  // 没有就新建一个
  const newOne = await store.createSession('新会话', store.options?.default_config as any)
  return newOne.id
}

async function doSend() {
  if (!canSend.value) return
  const q = inputText.value.trim()
  try {
    const sid = await ensureSession()
    if (!sid) {
      ElMessage.warning('会话创建失败，请检查后端服务')
      return
    }
    inputText.value = ''
    await store.sendQuestion(sid, q)
  } catch (e: any) {
    ElMessage.error(e?.message || '发送失败')
  }
}
</script>

<style lang="scss" scoped>
.chat-window {
  display: flex;
  height: 100%;
  background: #f5f7f9;
}

/* ---------- 欢迎页 ---------- */
.welcome {
  flex: 1;
  display: flex;
  align-items: center;
  padding: 40px 8% 20px;
  overflow-y: auto;

  .hero {
    text-align: center;
    margin-bottom: 30px;
    .hero-icon {
      width: 84px; height: 84px;
      display: inline-flex; align-items: center; justify-content: center;
      background: linear-gradient(135deg, #00897b, #00bfa5);
      border-radius: 22px;
      box-shadow: 0 8px 24px rgba(0, 137, 123, 0.35);
      margin-bottom: 16px;
    }
    h1 {
      font-size: 28px;
      color: #1f2937;
      margin-bottom: 6px;
    }
  }

  .quick-area {
    width: 100%;
    max-width: 1100px;
    h3 {
      font-size: 15px;
      color: #374151;
      margin: 10px 4px 14px;
      display: flex; align-items: center; gap: 6px;
    }
    .quick-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }
    .quick-card {
      cursor: pointer;
      transition: transform 0.15s, box-shadow 0.15s;
      border-radius: 10px;
      &:hover {
        transform: translateY(-2px);
        border-color: #00897b;
      }
      :deep(.el-card__body) { padding: 14px; }
      .card-label {
        color: #00695c;
        font-weight: 600;
        font-size: 14px;
        margin-bottom: 6px;
      }
      .card-example {
        color: #4b5563;
        font-size: 12.5px;
        line-height: 1.5;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
    }
  }
}

/* ---------- 消息流 ---------- */
.messages-scroll {
  width: 100%;
}
.messages-inner {
  max-width: 980px;
  margin: 0 auto;
  padding: 20px 16px 10px;
}

.typing-dot {
  padding-left: 56px;
  span {
    display: inline-block;
    width: 6px; height: 6px;
    margin-right: 4px;
    border-radius: 50%;
    background: #9ca3af;
    animation: blink 1.3s infinite;
  }
  span:nth-child(2) { animation-delay: 0.2s; }
  span:nth-child(3) { animation-delay: 0.4s; }
}
@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* ---------- 输入区 ---------- */
.input-area {
  flex-shrink: 0;
  padding: 12px 16px 16px;
  border-top: 1px solid var(--border-color);
  background: #fff;

  .quick-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
    .chip { cursor: pointer; }
  }

  .input-box {
    max-width: 980px;
    margin: 0 auto;
    display: flex;
    align-items: flex-end;
  }
  .ta-wrap {
    .ta-hint {
      display: flex; justify-content: space-between;
      font-size: 11px; padding: 2px 4px 0;
    }
  }
  .send-btn {
    height: 48px;
    padding: 0 20px;
    border-radius: 10px;
    font-weight: 600;
  }
}
</style>