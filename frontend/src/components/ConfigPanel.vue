<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="(v: any) => $emit('update:visible', v)"
    title="会话配置"
    width="520px"
    :close-on-click-modal="false"
    @open="loadLocal"
  >
    <el-form :model="form" label-width="140px" v-if="visible">
      <el-divider content-position="left">默认分析偏好</el-divider>

      <el-form-item label="默认电网类型">
        <el-select v-model="form.default_grid_type" class="w-full">
          <el-option
            v-for="g in grids"
            :key="g.value"
            :label="g.label"
            :value="g.value"
          >
            <span>{{ g.label }}</span>
            <span class="muted" style="float:right; font-size:12px;">{{ g.desc }}</span>
          </el-option>
        </el-select>
        <div class="muted" style="font-size:12px; margin-top:4px;">
          当用户问题里没提电网类型、也没有上下文时，用该电网兜底
        </div>
      </el-form-item>

      <el-divider content-position="left">界面显示</el-divider>

      <el-form-item label="工具详情默认展开">
        <el-switch v-model="form.ui_show_tool_details" active-text="展开" inactive-text="折叠" />
        <div class="muted" style="font-size:12px; margin-top:4px;">
          关闭时默认折叠工具卡片，AI回答更简洁
        </div>
      </el-form-item>

      <el-form-item label="表格最多显示行数">
        <el-slider
          v-model="form.ui_max_table_rows"
          :min="5" :max="100" :step="5"
          show-input
        />
      </el-form-item>

      <el-form-item label="UI主题">
        <el-radio-group v-model="form.ui_theme">
          <el-radio-button value="sgcc-green">国网绿</el-radio-button>
          <el-radio-button value="light">浅色</el-radio-button>
          <el-radio-button value="dark">深色(开发中)</el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useSessionStore } from '@/stores/session'
import type { SessionConfig } from '@/types'

const props = defineProps<{
  visible: boolean
  sessionId: string
}>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'updated'): void
}>()

const store = useSessionStore()
const saving = ref(false)

const grids = computed(() => store.options?.grids || [])
const defaultCfg = computed(
  () => store.options?.default_config || ({} as SessionConfig),
)

const form = reactive<SessionConfig>({
  default_grid_type: 'case30',
  ui_show_tool_details: true,
  ui_max_table_rows: 10,
  ui_theme: 'sgcc-green',
})

// 打开弹窗时，先读当前会话的配置（没有就用全局默认）
function loadLocal() {
  const current = store.currentConfig || {}
  Object.assign(form, defaultCfg.value, current)
}
watch(
  () => props.visible,
  (v) => { if (v) loadLocal() },
)

async function onSave() {
  if (!props.sessionId) return
  saving.value = true
  try {
    await store.updateSession(props.sessionId, { config: { ...form } })
    ElMessage.success('配置已保存')
    emit('updated')
    emit('update:visible', false)
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.w-full { width: 100%; }
</style>