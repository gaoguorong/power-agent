<template>
  <div class="app-root">
    <!-- ===== 顶部栏 ===== -->
    <header class="topbar">
      <div class="topbar-left">
        <el-button
          class="collapse-btn"
          :icon="Menu"
          text
          circle
          @click="sidebarCollapsed = !sidebarCollapsed"
        />
        <div class="brand">
          <svg viewBox="0 0 64 64" width="30" height="30">
            <path fill="#fff" d="M38 2L12 34h14l-4 28 30-36H34l4-24z" />
          </svg>
          <span v-if="!sidebarCollapsed">电网分析智能体</span>
        </div>
      </div>

      <div class="topbar-center">
        <el-dropdown trigger="click" @command="onGridChange" v-if="currentSession">
          <el-button class="grid-picker" plain>
            <el-icon><Setting /></el-icon>
            <span>当前会话：</span>
            <b>{{ currentSession.name }}</b>
            <el-icon><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="openConfig">
                <el-icon><Tools /></el-icon>会话配置
              </el-dropdown-item>
              <el-dropdown-item @click="doResetGrid">
                <el-icon><RefreshRight /></el-icon>重置电网
              </el-dropdown-item>
              <el-dropdown-item divided @click="doRename">
                <el-icon><Edit /></el-icon>重命名会话
              </el-dropdown-item>
              <el-dropdown-item @click="doDeleteSession">
                <el-icon><Delete /></el-icon>删除会话
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <div class="topbar-right">
        <el-tag
          size="small"
          :type="options?.llm_available ? 'success' : 'danger'"
          effect="dark"
          round
        >
          {{ options?.llm_available ? 'LLM 就绪' : 'LLM 未配置' }}
        </el-tag>
      </div>
    </header>

    <div class="body-wrap">
      <!-- ===== 左侧会话栏 ===== -->
      <aside
        class="sidebar"
        :class="{ collapsed: sidebarCollapsed }"
      >
        <Sidebar />
      </aside>

      <!-- ===== 中间聊天主区 ===== -->
      <main class="chat-main">
        <ChatWindow />
      </main>
    </div>

    <!-- ===== 会话配置弹窗 ===== -->
    <ConfigPanel
      v-model:visible="configVisible"
      :session-id="currentSessionId!"
      @updated="onConfigUpdated"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Menu, Setting, ArrowDown, Tools, RefreshRight, Edit, Delete,
} from '@element-plus/icons-vue'
import Sidebar from '@/components/Sidebar.vue'
import ChatWindow from '@/components/ChatWindow.vue'
import ConfigPanel from '@/components/ConfigPanel.vue'
import { useSessionStore } from '@/stores/session'
import { api } from '@/api'

const store = useSessionStore()
const sidebarCollapsed = ref(false)
const configVisible = ref(false)

const options = computed(() => store.options)
const currentSession = computed(() => store.currentSession)
const currentSessionId = computed(() => store.currentSessionId)

// 应用启动时：拉全局选项 + 会话列表
onMounted(async () => {
  let optionsOk = false
  try {
    await store.loadOptions()
    optionsOk = true
  } catch (e) {
    ElMessage.warning('获取初始化选项失败，检查后端是否启动')
  }
  try {
    await store.loadSessions()
  } catch (e) {
    // 列表失败无所谓，说不定是没配置 MySQL。没会话时界面会给引导。
  }
  // 兜底：如果完全没会话，立刻建一个默认的，让用户直接能问
  if (store.sessions.length === 0) {
    try {
      const defaultCfg = optionsOk ? store.options?.default_config : undefined
      await store.createSession('新会话', defaultCfg as any)
    } catch (e) {
      // 静默失败，等发送时再走 ensureSession 兜底
    }
  }
})

function openConfig() {
  configVisible.value = true
}

function onConfigUpdated() {
  ElMessage.success('配置已更新')
}

async function onGridChange() {
  // 目前这里没做电网切换，点一下主要是打开配置
  // （保留方法给后续扩展）
}

async function doResetGrid() {
  if (!currentSessionId.value) return
  try {
    await ElMessageBox.confirm(
      '确定要重置该会话的电网吗？对话历史保留，但电网状态会清空。',
      '重置电网',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
    await api.resetSessionGrid(currentSessionId.value)
    ElMessage.success('电网已重置')
  } catch { /* 用户取消 */ }
}

async function doRename() {
  if (!currentSessionId.value) return
  try {
    const { value } = await ElMessageBox.prompt(
      '输入新的会话名称',
      '重命名会话',
      {
        inputValue: currentSession.value?.name || '',
        inputPlaceholder: '会话名称',
        inputValidator: (v: string) => !!v.trim() || '名称不能为空',
      },
    )
    await store.updateSession(currentSessionId.value, { name: value.trim() })
    ElMessage.success('已重命名')
  } catch { /* 用户取消 */ }
}

async function doDeleteSession() {
  if (!currentSessionId.value) return
  try {
    await ElMessageBox.confirm(
      '删除后无法恢复，确定要删除该会话吗？',
      '删除会话',
      { type: 'error', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await store.deleteSession(currentSessionId.value)
  } catch { /* 用户取消 */ }
}
</script>

<style lang="scss" scoped>
.app-root {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--sgcc-bg);
}

/* ---------- 顶部栏 ---------- */
.topbar {
  height: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: linear-gradient(90deg, #00695c, #00897b);
  color: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  z-index: 50;

  .topbar-left {
    display: flex;
    align-items: center;
    gap: 8px;
    .collapse-btn {
      color: #fff;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 18px;
      font-weight: 600;
      padding-left: 6px;
    }
  }

  .grid-picker {
    background: rgba(255,255,255,0.15);
    border-color: rgba(255,255,255,0.3);
    color: #fff;
    b { color: #fff; margin: 0 2px; }
    &:hover {
      background: rgba(255,255,255,0.25);
      color: #fff;
    }
  }

  .topbar-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }
}

/* ---------- 主体 ---------- */
.body-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
}

.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: var(--sidebar-bg);
  color: #d1d5db;
  transition: width 0.2s ease;
  border-right: 1px solid #111827;
  &.collapsed {
    width: 0;
    overflow: hidden;
    border-right: none;
  }
}

.chat-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>