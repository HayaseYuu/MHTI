<script setup lang="ts">
import { NButton, NSpin } from 'naive-ui'
import type { HistoryBatchGroup } from '@/modules/history/types'

defineProps<{
  groups: HistoryBatchGroup[]
  loading: boolean
  disabled: boolean
}>()
defineEmits<{ select: [group: HistoryBatchGroup] }>()
</script>

<template>
  <div
    v-if="groups.length || loading"
    class="directory-groups"
    role="group"
    aria-label="按作品目录选择"
  >
    <span class="directory-label">按作品目录选择（当前页）</span>
    <NSpin v-if="loading" :size="16" />
    <NButton
      v-for="group in groups"
      :key="group.group_key"
      class="directory-button"
      size="small"
      secondary
      :disabled="disabled"
      :title="`${group.folder_name}：选中 ${group.record_ids.length} 条，可统一选择版本`"
      @click="$emit('select', group)"
    >
      <span class="directory-name">{{ group.folder_name }}</span>
      <span class="directory-count">{{ group.record_ids.length }} 条</span>
    </NButton>
  </div>
</template>

<style scoped>
.directory-groups {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2) 0;
}
.directory-label {
  font-size: var(--text-xs);
  color: var(--text-2);
}
.directory-name {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.directory-count {
  margin-left: var(--space-2);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
@media (max-width: 640px) {
  .directory-label {
    width: 100%;
  }
  .directory-name {
    max-width: 180px;
  }
}
</style>
