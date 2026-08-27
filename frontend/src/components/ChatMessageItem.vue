<template>
  <div class="msg-row" :class="message.role">
    <!-- ====== 头像 ====== -->
    <div class="avatar" :class="message.role">
      <el-icon v-if="message.role === 'user'" :size="18"><UserFilled /></el-icon>
      <svg v-else viewBox="0 0 64 64" width="18" height="18">
        <path fill="#fff" d="M38 2L12 34h14l-4 28 30-36H34l4-24z" />
      </svg>
    </div>

    <!-- ====== 气泡主体 ====== -->
    <div class="bubble-wrap flex-1">
      <div class="role-name">{{ roleLabel }}</div>
      <div class="bubble">
        <!-- 文本内容（支持换行，简单处理即可，marked 暂时不用） -->
        <p
          v-if="displayText"
          class="content-text"
          v-html="renderTextAsHtml(displayText)"
        />

        <!-- ========= AI 专用：工具调用链卡片 ========= -->
        <div v-if="isAI && message.tool_runs && message.tool_runs.length" class="tools-section">
          <div
            class="tool-head"
            @click="showToolDetails = !showToolDetails"
          >
            <el-icon class="fold-icon" :class="{ expanded: showToolDetails }">
              <ArrowRight />
            </el-icon>
            <span>
              本次调用
              <b>{{ message.tool_runs.length }}</b>
              个工具
            </span>
            <span
              class="tool-status-tag"
              v-for="tc in toolCountByStatus"
              :key="tc.status"
            >
              <el-tag size="small" :type="statusTagType(tc.status)" effect="light">
                {{ statusLabel(tc.status) }} {{ tc.count }}
              </el-tag>
            </span>
          </div>

          <div v-show="showToolDetails" class="tool-list">
            <div
              v-for="(t, i) in message.tool_runs"
              :key="i"
              class="tool-item"
              :class="t.status"
            >
              <div class="tool-title">
                <el-icon class="icon" :class="statusIconClass(t.status)">
                  <component :is="statusIcon(t.status)" />
                </el-icon>
                <span class="tool-name">{{ t.name }}</span>
                <span class="tool-duration muted" v-if="t.start_time && t.end_time">
                  耗时 {{ (t.end_time - t.start_time) / 1000 }}s
                </span>
              </div>

              <div class="tool-arg" v-if="t.input && Object.keys(t.input).length">
                <span class="k">参数：</span>
                <code>{{ stringify(t.input) }}</code>
              </div>

              <div class="tool-out" v-if="t.output">
                <span class="k">结果：</span>
                <!-- 如果是数组/对象，给个可折叠的小表格/代码；否则直接文本 -->
                <ToolOutputView :output="t.output" :max-rows="maxRows" />
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, inject, provide } from 'vue'
import {
  UserFilled, ArrowRight, Loading, CircleCheck, WarningFilled,
} from '@element-plus/icons-vue'
import ToolOutputView from './ToolOutputView.vue'
import type { ChatMessage } from '@/types'
import { useSessionStore } from '@/stores/session'

const props = defineProps<{
  message: ChatMessage
}>()

const store = useSessionStore()

const roleLabel = computed(() => {
  if (props.message.role === 'user') return '我'
  if (props.message.role === 'assistant') return '智能体'
  if (props.message.role === 'tool') return `工具结果：${props.message.tool_name}`
  return props.message.role
})

const isAI = computed(() => props.message.role === 'assistant')

const displayText = computed(() => {
  const c = props.message.content
  if (c == null) return ''
  if (typeof c === 'string') return c
  if (Array.isArray(c)) {
    return c.map((x) => (typeof x === 'string' ? x : x?.text || '')).join('')
  }
  return String(c)
})

// 默认显示工具详情与否：看会话配置里 ui_show_tool_details
const showToolDetails = ref(
  !!store.currentConfig.ui_show_tool_details,
)

// 切换会话后重新默认一次
watch(
  () => store.currentConfig.ui_show_tool_details,
  (v) => { showToolDetails.value = !!v },
)

// 工具调用项按 status 统计
const toolCountByStatus = computed(() => {
  const m = new Map()
  for (const t of props.message.tool_runs || []) {
    m.set(t.status, (m.get(t.status) || 0) + 1)
  }
  return Array.from(m, ([status, count]) => ({ status, count }))
})

const maxRows = computed(() =>
  Number(store.currentConfig.ui_max_table_rows) || 10,
)

// --- 小工具 ---
function renderTextAsHtml(text: string) {
  // 轻量文本处理：< & > 转义 + 识别换行，其他不做（防止 XSS，工具结果里的表格/JSON 用 ToolOutputView 处理）
  const esc = (s: string) =>
    s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  return esc(text || '').replace(/\n/g, '<br>')
}
function stringify(obj: any) {
  try {
    return JSON.stringify(obj)
  } catch {
    return String(obj)
  }
}

function statusIcon(s: string) {
  if (s === 'running') return Loading
  if (s === 'error') return WarningFilled
  return CircleCheck
}
function statusIconClass(s: string) {
  return s
}
function statusTagType(s: string) {
  if (s === 'running') return 'warning'
  if (s === 'error') return 'danger'
  return 'success'
}
function statusLabel(s: string) {
  if (s === 'running') return '进行中'
  if (s === 'error') return '失败'
  return '成功'
}
</script>

<style lang="scss" scoped>
.msg-row {
  display: flex;
  gap: 12px;
  margin-bottom: 22px;
  align-items: flex-start;

  &.user {
    flex-direction: row-reverse;
    .bubble-wrap { text-align: right; }
    .role-name { padding-right: 6px; }
    .bubble {
      background: var(--bubble-user-bg);
      color: #fff;
      border-radius: 14px 14px 4px 14px;
      margin-left: auto;
      text-align: left;
      .content-text { color: #fff; }
    }
  }
}

.avatar {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  &.user {
    background: linear-gradient(135deg, #4b5563, #6b7280);
  }
  &.assistant {
    background: linear-gradient(135deg, #00695c, #00897b);
    box-shadow: 0 2px 6px rgba(0, 137, 123, 0.35);
  }
  &.tool {
    background: #6366f1;
  }
}

.bubble-wrap {
  max-width: 86%;
  display: flex;
  flex-direction: column;
  .role-name {
    font-size: 12px;
    color: #6b7280;
    margin-bottom: 4px;
    padding-left: 2px;
  }
}

.bubble {
  display: inline-block;
  background: var(--bubble-assistant-bg);
  padding: 12px 14px;
  border-radius: 6px 14px 14px 14px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
  border: 1px solid var(--border-color);
  white-space: normal;
  text-align: left;
  max-width: 100%;

  .content-text {
    font-size: 14px;
    line-height: 1.7;
    color: var(--text-primary);
    word-break: break-word;
  }
}

/* ===== 工具调用链 ===== */
.tools-section {
  margin-top: 12px;
  border-top: 1px dashed var(--border-color);
  padding-top: 10px;

  .tool-head {
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #4b5563;
    padding: 4px 6px;
    border-radius: 6px;
    &:hover { background: #f3f4f6; }
    b { color: #00695c; margin: 0 2px; }
    .fold-icon {
      transition: transform 0.2s;
      &.expanded { transform: rotate(90deg); color: #00695c; }
    }
    .tool-status-tag { margin-left: 6px; }
  }

  .tool-list {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .tool-item {
    border: 1px solid var(--border-color);
    background: #fafbfc;
    border-radius: 8px;
    padding: 8px 10px;
    border-left-width: 4px;
    &.running { border-left-color: #e6a23c; background: #fdf6ec; }
    &.ok      { border-left-color: #00897b; }
    &.error   { border-left-color: #f56c6c; background: #fef0f0; }

    .tool-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      margin-bottom: 4px;
      .icon { font-size: 14px; }
      .icon.running { color: #e6a23c; animation: rot 0.8s linear infinite; }
      .icon.ok { color: #00897b; }
      .icon.error { color: #f56c6c; }
      .tool-name {
        font-weight: 600;
        color: #1f2937;
        font-family: 'JetBrains Mono', Consolas, monospace;
      }
      .tool-duration { margin-left: auto; }
    }
    .tool-arg, .tool-out {
      font-size: 12px;
      line-height: 1.5;
      color: #4b5563;
      margin: 3px 0;
      .k { color: #6b7280; margin-right: 4px; }
      code {
        background: #f3f4f6;
        padding: 1px 6px;
        border-radius: 4px;
        font-family: Consolas, monospace;
        font-size: 11.5px;
        color: #374151;
      }
    }
  }
}

@keyframes rot {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>