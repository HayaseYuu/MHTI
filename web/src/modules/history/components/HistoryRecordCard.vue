<script setup lang="ts">
/**
 * 刮削记录移动端卡片（HistoryPage 移动视图）
 *
 * 纯展示 + 事件转发。信息顺序按移动端阅读习惯重排：
 * 标题 → 季集与时间 → 文件夹 → 状态与操作。
 * 触发方式降级为中性小字（原本是一枚彩色 NTag，与状态徽章抢注意力）。
 *
 * 操作与桌面表格同源：处理（仅需人工介入时）/ 重刮（点开弹窗填 TMDB ID）/
 * 更多（重新整理、删除文件、删除记录）。移动端没有 hover，所以按钮常显。
 */
import { NButton, NCheckbox, NIcon } from 'naive-ui'
import { ChevronForwardOutline } from '@vicons/ionicons5'
import type { HistoryRecord } from '@/modules/history/types'
import RecordActions from '@/modules/history/components/RecordActions.vue'
import StatusBadge from '@/shared/components/business/StatusBadge.vue'
import TouchCard from '@/shared/components/base/TouchCard.vue'
import {
  episodeLabel,
  formatDuration,
  formatTime,
  getFolder,
  getStatusBadge,
  getTimeoutStopLabel,
  getTriggerLabel,
  resolveDurationSeconds,
} from '@/modules/history/utils'

defineProps<{
  record: HistoryRecord
  /** 重刮 / 重新整理进行中：锁住操作避免重复提交 */
  busy?: boolean
  /** 每秒自增的时间戳：驱动耗时实时跳动（由页面统一持有定时器） */
  nowTick: number
  /** 批量重试的勾选态 */
  checked?: boolean
  /** 是否可勾选（状态可重试且匹配信息齐全） */
  selectable?: boolean
}>()

const emit = defineEmits<{
  click: []
  handle: []
  /** 重刮：只请求打开弹窗，ID/季/集由弹窗收集后回传页面 */
  rescape: []
  reorganize: []
  'delete-files': []
  delete: []
  'update:checked': [value: boolean]
}>()
</script>

<template>
  <TouchCard clickable @click="emit('click')">
    <div class="card">
      <div class="card-top">
        <span class="card-id">#{{ record.display_id }}</span>
        <StatusBadge
          :status="getStatusBadge(record.status).status"
          :text="getStatusBadge(record.status).text"
          size="small"
        />
        <!-- 批量重试勾选：移动端没有悬浮，勾选框常显在卡片右侧 -->
        <NCheckbox
          class="card-check"
          :checked="checked"
          :disabled="!selectable"
          :aria-label="`选择记录 #${record.display_id}`"
          @click.stop
          @update:checked="emit('update:checked', $event)"
        />
      </div>

      <p class="card-title">{{ record.title || '未知标题' }}</p>

      <p class="card-meta">
        <span v-if="episodeLabel(record)" class="card-episode">{{ episodeLabel(record) }}</span>
        <span>{{ formatTime(record.executed_at) }}</span>
        <span class="card-sep" aria-hidden="true">·</span>
        <span class="card-duration">耗时 {{ formatDuration(resolveDurationSeconds(record, nowTick)) }}</span>
        <span class="card-sep" aria-hidden="true">·</span>
        <span>{{ getTriggerLabel(record) }}</span>
      </p>

      <p v-if="getTimeoutStopLabel(record)" class="card-stop">{{ getTimeoutStopLabel(record) }}</p>

      <p class="card-folder">{{ getFolder(record.folder_path) }}</p>

      <div class="card-actions" @click.stop>
        <NButton
          v-if="record.status === 'pending_action' || record.status === 'failed' || record.status === 'timeout'"
          size="tiny"
          type="primary"
          :disabled="busy"
          @click="emit('handle')"
        >
          处理
        </NButton>
        <NButton
          size="tiny"
          quaternary
          :disabled="busy"
          :aria-label="`按元数据 ID 重刮 #${record.display_id}`"
          @click="emit('rescape')"
        >
          重刮
        </NButton>
        <RecordActions
          :record="record"
          :busy="busy"
          @reorganize="emit('reorganize')"
          @delete-files="emit('delete-files')"
          @delete="emit('delete')"
        />
      </div>
    </div>

    <template #suffix>
      <NIcon :component="ChevronForwardOutline" class="chevron" :size="14" />
    </template>
  </TouchCard>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.card-top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.card-check {
  margin-left: auto;
}

.card-id {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-3);
}

.card-title {
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  line-height: var(--leading-snug);
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-3);
}

/* 等宽数字：读秒时整行不会左右抽动 */
.card-duration {
  font-variant-numeric: tabular-nums;
}

.card-episode {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}

.card-sep {
  color: var(--text-3);
}

.card-folder {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 超时节点：与列表同一语义色，提醒「点进去重试」 */
.card-stop {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--warning-500);
  overflow-wrap: anywhere;
}

.card-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.chevron {
  flex-shrink: 0;
  color: var(--text-3);
}
</style>
