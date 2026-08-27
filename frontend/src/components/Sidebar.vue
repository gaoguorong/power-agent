<template>
  <div class="sidebar-inner flex-col h-full">
    <!-- ===== 顶部：新建按钮 ===== -->
    <div class="top-area">
      <el-button
        type="primary"
        class="new-btn"
        :icon="Plus"
        @click="createNewSession"
      >
        新建会话
      </el-button>
    </div>

    <!-- ===== 搜索框 ===== -->
    <div class="search-wrap">
      <el-input
        v-model="keyword"
        placeholder="搜索会话..."
        clearable
        :prefix-icon="Search"
        size="default"
        class="search-input"
      />
    </div>

    <!-- ===== 会话列表 ===== -->
    <el-scrollbar class="session-scroll">
      <ul v-if="filteredSessions.length > 0" class="session-list">
        <li
          v-for="s in filteredSessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === store.currentSessionId }"
          @click="pickSession(s.id)"
        >
          <div class="item-head flex justify-between items-center">
            <span class="name truncate">
              <el-icon class="chat-icon"><ChatDotRound /></el-icon>
              {{ s.name }}
            </span>
            <el-dropdown
              trigger="click"
              @click.stop
              @command="(cmd: any) => handleItemAction(cmd, s)"
            >
              <el-button
                class="more-btn"
                link
                :icon="MoreFilled"
                @click.stop
              />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">
                    <el-icon><Edit /></el-icon>重命名
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided>
                    <el-icon><Delete /></el-icon>删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="preview muted truncate">
            {{ s.last_message || '（暂无消息）' }}
          </div>
          <div class="meta muted">
            <span>{{ s.message_count }} 条消息</span>
            <span>{{ formatTime(s.updated_at) }}</span>
          </div>
        </li>
      </ul>
      <el-empty
        v-else
        description="还没有会话"
        :image-size="90"
        class="empty-hint"
      />
    </el-scrollbar>

    <!-- ===== 底部 ===== -->
    <div class="bottom-area muted">
      <el-tag size="small" effect="plain" type="info">
        <el-icon><Cpu /></el-icon>
        Power Agent · v1.0
      </el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Search, ChatDotRound, MoreFilled, Edit, Delete, Cpu,
} from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { useSessionStore } from '@/stores/session'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const store = useSessionStore()
const keyword = ref('')

const filteredSessions = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return store.sessions
  return store.sessions.filter(
    (s) =>
      s.name.toLowerCase().includes(kw) ||
      s.last_message.toLowerCase().includes(kw),
  )
})

async function createNewSession() {
  try {
    await store.createSession('新会话', store.options?.default_config as any)
  } catch (e) {
    ElMessage.error('创建会话失败')
  }
}

async function pickSession(id: string) {
  await store.selectSession(id)
}

async function handleItemAction(cmd: string, s: any) {
  if (cmd === 'rename') {
    try {
      const { value } = await ElMessageBox.prompt('新的会话名称', '重命名', {
        inputValue: s.name,
        inputValidator: (v: string) => !!v.trim() || '名称不能为空',
      })
      await store.updateSession(s.id, { name: value.trim() })
      ElMessage.success('已重命名')
    } catch {}
  } else if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm(`确定删除会话【${s.name}】？`, '删除', {
        type: 'error',
      })
      await store.deleteSession(s.id)
    } catch {}
  }
}

function formatTime(t: string | null) {
  if (!t) return ''
  return dayjs(t).fromNow()
}
</script>

<style lang="scss" scoped>
.sidebar-inner {
  height: 100%;
  display: flex;
  padding: 14px 12px 10px;
}

.top-area {
  flex-shrink: 0;
  margin-bottom: 12px;
  .new-btn {
    width: 100%;
    height: 40px;
    font-weight: 600;
    border-radius: 8px;
  }
}

.search-wrap {
  flex-shrink: 0;
  margin-bottom: 10px;
  :deep(.el-input__wrapper) {
    background: rgba(255, 255, 255, 0.06);
    box-shadow: none;
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #fff;
  }
  :deep(.el-input__inner) {
    color: #e5e7eb;
  }
  :deep(.el-input__inner::placeholder) {
    color: #9ca3af;
  }
}

.session-scroll {
  flex: 1;
  min-height: 0;
  margin-right: -4px;
}

.session-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;

  &:hover {
    background: var(--sidebar-hover);
  }
  &.active {
    background: linear-gradient(
      90deg,
      rgba(0, 137, 123, 0.35),
      rgba(0, 137, 123, 0.15)
    );
    border-color: rgba(0, 137, 123, 0.5);
  }

  .item-head {
    .name {
      font-size: 14px;
      color: #f3f4f6;
      display: flex;
      align-items: center;
      gap: 6px;
      max-width: calc(100% - 28px);
      .chat-icon { color: #00bfa5; }
    }
    .more-btn {
      color: #9ca3af;
      padding: 2px 4px;
    }
  }
  .preview {
    font-size: 12px;
    color: #9ca3af;
    margin: 4px 0 6px;
    line-height: 1.4;
  }
  .meta {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: #6b7280;
  }
}

.empty-hint {
  padding-top: 30px;
  :deep(.el-empty__description) { color: #9ca3af; }
}

.bottom-area {
  flex-shrink: 0;
  padding: 10px 4px 2px;
  text-align: center;
  font-size: 12px;
  opacity: 0.7;
}
</style>