<template>
  <!-- 智能展示工具输出：
       - 如果是对象含 data[] / rows[] → 表格
       - 如果是纯数组 → 表格
       - 否则 → 代码块（JSON或纯文本） -->
  <div class="tool-output-view">

    <!-- 情况 A：直接就是纯字符串（比如大文本摘要） -->
    <div v-if="isPlainString" class="plain-text">
      {{ output }}
    </div>

    <!-- 情况 B：找到了表格数据列 → el-table -->
    <el-table
      v-else-if="tableData && tableData.length"
      :data="tableData.slice(0, maxRows)"
      size="small"
      stripe
      border
      max-height="260"
      style="width: 100%; margin-top: 4px"
    >
      <el-table-column
        v-for="col in columns"
        :key="col"
        :prop="col"
        :label="col"
        show-overflow-tooltip
        :formatter="formatCell"
      />
    </el-table>
    <div v-if="tableData && tableData.length > maxRows" class="trunc-hint muted">
      共 {{ tableData.length }} 条，仅显示前 {{ maxRows }} 条
    </div>

    <!-- 情况 C：字典结构，但不是表格 → 折叠面板 -->
    <div v-else-if="isObject" class="kv-wrap">
      <el-collapse size="small">
        <el-collapse-item title="查看详细 JSON" name="json">
          <pre class="code-block">{{ stringifyPretty(output) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 情况 D：兜底 -->
    <pre v-else class="code-block">{{ stringifyPretty(output) }}</pre>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    output: any
    maxRows?: number
  }>(),
  { maxRows: 10 },
)

// 先规范化 output：传进来可能是 JSON 字符串
const normalized = computed(() => {
  if (typeof props.output === 'string') {
    try { return JSON.parse(props.output) } catch {}
  }
  return props.output
})

const isPlainString = computed(
  () => typeof normalized.value === 'string' && !looksLikeJson(normalized.value),
)

const isObject = computed(
  () => normalized.value && typeof normalized.value === 'object' && !Array.isArray(normalized.value),
)

/**
 * 从各种工具输出格式里找"表格数组"
 * pandapower/国网工具常见返回：
 *   { success:true, data: [...] } / { table: [...] } / { rows: [...] } / { lines:[...] }
 *   或者直接就是数组
 */
const tableData = computed<any[]>(() => {
  const v = normalized.value
  if (Array.isArray(v)) return v
  if (!v || typeof v !== 'object') return []
  const keys = ['rows', 'data', 'items', 'list', 'lines', 'buses', 'elements']
  for (const k of keys) {
    if (Array.isArray(v[k])) return v[k]
  }
  // 兜底：找第一个数组值
  for (const k of Object.keys(v)) {
    if (Array.isArray(v[k]) && v[k].length > 0 && typeof v[k][0] === 'object') {
      return v[k]
    }
  }
  return []
})

const columns = computed<string[]>(() => {
  const rows = tableData.value
  if (!rows.length) return []
  // 取第一条的所有 keys 作为列
  const r0 = rows[0]
  if (!r0 || typeof r0 !== 'object') return []
  return Object.keys(r0)
})

function formatCell(row: any, col: any, cellVal: any) {
  if (cellVal == null) return '-'
  if (typeof cellVal === 'number') {
    // 浮点数保留3位
    if (!Number.isInteger(cellVal)) return cellVal.toFixed(3)
  }
  return String(cellVal)
}

// --- helpers ---
function looksLikeJson(s: string) {
  const t = s.trim()
  return (t.startsWith('{') && t.endsWith('}')) || (t.startsWith('[') && t.endsWith(']'))
}
function stringifyPretty(o: any) {
  try {
    if (typeof o === 'string') return o
    return JSON.stringify(o, null, 2)
  } catch {
    return String(o)
  }
}
</script>

<style lang="scss" scoped>
.tool-output-view {
  font-size: 12px;
  margin-left: 4px;
  margin-top: 2px;
  display: block;
}

.plain-text {
  padding: 4px 8px;
  background: #fff;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  line-height: 1.5;
  white-space: pre-wrap;
  color: #374151;
}

.code-block {
  background: #1e293b;
  color: #e5e7eb;
  padding: 10px 12px;
  border-radius: 6px;
  font-family: Consolas, 'JetBrains Mono', monospace;
  font-size: 11.5px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 260px;
  margin: 4px 0;
}

.trunc-hint {
  text-align: right;
  font-size: 11px;
  margin-top: 4px;
}

.kv-wrap { margin-top: 4px; }
</style>