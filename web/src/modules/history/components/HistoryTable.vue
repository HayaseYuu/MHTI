<script setup lang="ts">
/**
 * 刮削记录桌面表格（HistoryPage 桌面视图）
 *
 * 列定义随组件；:deep 表格样式随之迁入（父组件 scoped 属性不作用于子组件内部）。
 *
 * 视觉取舍：
 * - 状态列由彩色 NTag 改为 StatusBadge（语义点 + 文字）。表格里每行一个彩色胶囊
 *   会把整列变成色块，反而淡化"失败"这一真正需要注意的状态。
 * - 触发方式只是元数据标注，用中性小字，不再占用颜色语义。
 * - 行操作分两层：重刮留在行内（点开弹窗填 TMDB ID，弹窗里可搜 TMDB）；
 *   重新整理 / 删除文件 / 删除记录三个低频操作用「更多」，其中删除记录为危险色。
 * - 删除按钮常态可见（压低存在感）：纯 hover 显现的按钮在触屏平板上永远点不到。
 * - 「耗时」列按 nowTick 每秒重算：running 记录用 started_at 现场推算，
 *   任务跑多久数字就跳多久，不再等任务结束才从 0.0s 一下变成最终值。
 */
import { computed, h } from 'vue'
import { NButton, NDataTable, type DataTableColumns } from 'naive-ui'
import type { HistoryRecord } from '@/modules/history/types'
import {
  formatDuration,
  episodeLabel,
  formatTime,
  getFolder,
  getStatusBadge,
  getTimeoutStopLabel,
  getTriggerLabel,
  resolveDurationSeconds,
} from '@/modules/history/utils'
import RecordActions from '@/modules/history/components/RecordActions.vue'
import StatusBadge from '@/shared/components/business/StatusBadge.vue'

const props = defineProps<{
  records: HistoryRecord[]
  loading: boolean
  /** 正在处理的记录 id：该行的操作按钮禁用，避免重复提交 */
  busyId?: string | null
  /** 每秒自增的时间戳：驱动「耗时」列实时跳动（由页面统一持有定时器） */
  nowTick: number
  /** 已勾选的记录 id（批量重试用） */
  checkedKeys?: string[]
  /** 该行是否可勾选（状态可重试且匹配信息齐全） */
  selectable?: (record: HistoryRecord) => boolean
}>()

const emit = defineEmits<{
  'row-click': [record: HistoryRecord]
  handle: [record: HistoryRecord]
  /** 重刮：只请求打开弹窗，ID/季/集由弹窗收集后回传页面 */
  rescape: [record: HistoryRecord]
  reorganize: [record: HistoryRecord]
  'delete-files': [record: HistoryRecord]
  delete: [record: HistoryRecord]
  'update:checkedKeys': [keys: string[]]
}>()

/**
 * 整行点击进详情，但勾选框与行内按钮不穿透：
 * 表格把行点击挂在 row-props 上，点勾选框会连着触发一次导航。
 */
function onRowClick(event: MouseEvent, row: HistoryRecord) {
  const target = event.target as HTMLElement | null
  if (target?.closest('.n-checkbox, .n-data-table-td--selection, button, a')) return
  emit('row-click', row)
}


/** 失败与超时需要人工介入，主操作按钮因此用于这两类状态 */
function needsManualAction(row: HistoryRecord): boolean {  return row.status === 'pending_action' || row.status === 'failed' || row.status === 'timeout'
}

// 列定义放 computed：耗时列依赖 nowTick，定时器一停就不再重算
// （假设用静态数组 + render 里读 ref，靠 naive 内部组件的渲染副作用命中，链路不稳）
const columns = computed<DataTableColumns<HistoryRecord>>(() => {
  const nowMs = props.nowTick
  return [
    {
      // 批量重试的勾选列：只有状态可重试且匹配信息齐全的行可选
      type: 'selection',
      width: 40,
      disabled: (row) => !(props.selectable?.(row) ?? false),
    },
    {
      title: 'ID',
      key: 'display_id',
      width: 76,
      render: (row) => h('span', { class: 'cell-id' }, `#${row.display_id}`),
    },
    {
      title: '名称',
      key: 'title',
      ellipsis: { tooltip: true },
      render: (row) => row.title || '—',
    },
    {
      title: '季/集',
      key: 'season_episode',
      width: 88,
      render: (row) => h('span', { class: 'cell-mono' }, episodeLabel(row) ?? '—'),
    },
    {
      title: '文件夹',
      key: 'folder',
      width: 220,
      ellipsis: { tooltip: true },
      render: (row) => h('span', { class: 'cell-muted' }, getFolder(row.folder_path)),
    },
    {
      title: '触发',
      key: 'trigger',
      width: 72,
      render: (row) => h('span', { class: 'cell-muted' }, getTriggerLabel(row)),
    },
    {
      title: '状态',
      key: 'status',
      width: 104,
      render: (row) => {
        const badge = getStatusBadge(row.status)
        const stopLabel = getTimeoutStopLabel(row)
        return h('div', { class: 'cell-status' }, [
          h(StatusBadge, {
            status: badge.status,
            text: badge.text,
            size: 'small',
          }),
          // 超时记录直接标出卡在哪一步：不用点进详情才知道该重试什么
          stopLabel ? h('span', { class: 'cell-stop' }, stopLabel) : null,
        ])
      },
    },
    {
      title: '执行时间',
      key: 'executed_at',
      width: 168,
      render: (row) => h('span', { class: 'cell-muted' }, formatTime(row.executed_at)),
    },
    {
      title: '耗时',
      key: 'duration',
      width: 72,
      render: (row) =>
        h('span', { class: 'cell-mono' }, formatDuration(resolveDurationSeconds(row, nowMs))),
    },
    {
      title: '',
      key: 'actions',
      width: 156,
      render: (row) => {
        // 行内点开的 popover / 下拉自带遮罩层，点击不能再冒泡成「进入详情」
        const stop = (fn: () => void) => (e: Event) => {
          e.stopPropagation()
          fn()
        }
        return h('div', { class: 'cell-actions' }, [
          needsManualAction(row)
            ? h(
                NButton,
                {
                  size: 'tiny',
                  type: 'primary',
                  disabled: props.busyId === row.id,
                  onClick: stop(() => emit('handle', row)),
                },
                { default: () => '处理' },
              )
            : null,
          h(
            NButton,
            {
              size: 'tiny',
              quaternary: true,
              disabled: props.busyId === row.id,
              'aria-label': `按元数据 ID 重刮 #${row.display_id}`,
              onClick: stop(() => emit('rescape', row)),
            },
            { default: () => '重刮' },
          ),
          h(RecordActions, {
            record: row,
            busy: props.busyId === row.id,
            onReorganize: () => emit('reorganize', row),
            'onDelete-files': () => emit('delete-files', row),
            onDelete: () => emit('delete', row),
          }),
        ])
      },
    },
  ]
})
</script>

<template>
  <div class="history-table">
    <NDataTable
      :columns="columns"
      :data="records"
      :loading="loading"
      :row-key="(row: HistoryRecord) => row.id"
      :checked-row-keys="checkedKeys ?? []"
      :bordered="false"
      size="small"
      :row-props="(row: HistoryRecord) => ({ style: 'cursor: pointer', onClick: (e: MouseEvent) => onRowClick(e, row) })"
      @update:checked-row-keys="emit('update:checkedKeys', $event as string[])"
    />
  </div>
</template>

<style scoped>
.history-table :deep(.n-data-table-th) {
  font-size: var(--text-xs);
  letter-spacing: 0.02em;
}

/* 行内操作：右对齐，靠间距区分主次，不给次要按钮加底色 */
.history-table :deep(.cell-actions) {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  justify-content: flex-end;
}

/* 状态列：徽章 + 超时节点的两行排版 */
.history-table :deep(.cell-status) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.history-table :deep(.cell-stop) {
  font-size: var(--text-xs);
  color: var(--warning-500);
  overflow-wrap: anywhere;
}

/* 次要列统一降一档字色，主列（名称）保持主色，层次不靠加粗堆叠 */
.history-table :deep(.cell-muted) {
  color: var(--text-2);
  font-size: var(--text-sm);
}

.history-table :deep(.cell-mono) {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.history-table :deep(.cell-id) {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-3);
}
</style>
