<script setup lang="ts">
/**
 * 预览步骤 - 配置摘要卡片
 *
 * 纯展示：路径、整理模式、空目录策略、高级设置状态。
 * linkModeLabel 的兜底 `|| formData.link_mode` 原样保留（未知模式时显示数字）。
 */
import { computed } from 'vue'
import { NCard, NDescriptions, NDescriptionsItem, NIcon, NTag } from 'naive-ui'
import {
  CheckmarkCircleOutline,
  CloseCircleOutline,
  DocumentOutline,
  FolderOutline,
  LinkOutline,
  SettingsOutline,
} from '@vicons/ionicons5'
import { LinkMode } from '@/modules/scrape/types'
import type { ManualJobAdvancedSettings } from '@/modules/scrape/types'
import { LINK_MODE_LABELS } from '@/modules/scrape/constants'

const props = defineProps<{
  formData: {
    scan_path: string
    target_folder: string
    metadata_dir: string
    link_mode: LinkMode
    delete_empty_parent: boolean
    r18: boolean
    ai_assist: boolean
  }
  advancedSettings: ManualJobAdvancedSettings | null
}>()

// 链接模式显示名称
const linkModeLabel = computed(
  () => LINK_MODE_LABELS[props.formData.link_mode] || props.formData.link_mode,
)
</script>

<template>
  <NCard class="summary-card" :bordered="false">
    <template #header>
      <div class="card-header">
        <NIcon :component="CheckmarkCircleOutline" class="header-icon" />
        <span>配置摘要</span>
      </div>
    </template>
    <NDescriptions :column="1" label-placement="left" :label-style="{ width: '100px' }">
      <NDescriptionsItem label="刮削路径">
        <div class="path-value">
          <NIcon :component="FolderOutline" />
          <span>{{ formData.scan_path || '-' }}</span>
        </div>
      </NDescriptionsItem>
      <NDescriptionsItem label="整理目录">
        <div class="path-value">
          <NIcon :component="FolderOutline" />
          <span>{{ formData.target_folder || '-' }}</span>
        </div>
      </NDescriptionsItem>
      <NDescriptionsItem v-if="formData.metadata_dir" label="元数据目录">
        <div class="path-value">
          <NIcon :component="DocumentOutline" />
          <span>{{ formData.metadata_dir }}</span>
        </div>
      </NDescriptionsItem>
      <NDescriptionsItem label="刮削模式">
        <NTag :type="formData.r18 ? 'warning' : 'info'" size="small" round>
          {{ formData.r18 ? 'R18 · TMDB' : '表番 · TMDB + AniList' }}
        </NTag>
      </NDescriptionsItem>
      <NDescriptionsItem label="AI 兜底">
        <NTag :type="formData.ai_assist ? 'info' : 'default'" size="small" round>
          {{ formData.ai_assist ? '允许辅助 · 需全局启用与 Key' : '已禁用' }}
        </NTag>
      </NDescriptionsItem>
      <NDescriptionsItem label="整理模式">
        <NTag type="info" size="small" round>
          <template #icon>
            <NIcon :component="LinkOutline" />
          </template>
          {{ linkModeLabel }}
        </NTag>
      </NDescriptionsItem>
      <NDescriptionsItem v-if="formData.link_mode === LinkMode.MOVE" label="空目录删除">
        <NTag :type="formData.delete_empty_parent ? 'success' : 'default'" size="small" round>
          <template #icon>
            <NIcon
              :component="formData.delete_empty_parent ? CheckmarkCircleOutline : CloseCircleOutline"
            />
          </template>
          {{ formData.delete_empty_parent ? '移动后自动删除' : '保留空目录' }}
        </NTag>
      </NDescriptionsItem>
      <NDescriptionsItem label="高级设置">
        <NTag :type="advancedSettings ? 'success' : 'default'" size="small" round>
          <template #icon>
            <NIcon :component="SettingsOutline" />
          </template>
          {{ advancedSettings ? '已自定义' : '使用全局配置' }}
        </NTag>
      </NDescriptionsItem>
    </NDescriptions>
  </NCard>
</template>

<style scoped>
.summary-card {
  background: var(--bg-subtle);
  border-radius: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.header-icon {
  font-size: 18px;
  color: var(--brand-500);
}

.path-value {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 13px;
  color: var(--text-2);
  word-break: break-all;
}

.path-value :deep(.n-icon) {
  flex-shrink: 0;
  color: var(--brand-500);
}

/* naive 自身的 padding 规则是 0,5,0（.n-descriptions .n-descriptions-table-wrapper
   .n-descriptions-table .n-descriptions-table-row .n-descriptions-table-content），
   用 :deep 提升到 0,2,0 永远输，属静默失效。改为在目标元素上覆写 naive 的
   CSS 变量：变量在使用它的元素上解析，不受选择器特异性影响。
   注：column=1 + label-placement=left 时标签与内容共用同一个 td
   （.n-descriptions-table-content），不存在 .n-descriptions-table-header 单元格。 */
:deep(.n-descriptions-table-content) {
  --n-td-padding: 8px 0;
}
</style>
