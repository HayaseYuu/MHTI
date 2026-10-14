<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NButton, NModal, NSpace } from 'naive-ui'
import type {
  HistoryBatchGroup,
  TMDBSearchResult,
} from '@/modules/history/types'
import SearchResultList from '@/modules/history/components/SearchResultList.vue'
import MetadataSourceBadge from '@/shared/components/business/MetadataSourceBadge.vue'

const props = defineProps<{
  show: boolean
  group: HistoryBatchGroup | null
  loading: boolean
  progressText: string
}>()
const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [result: TMDBSearchResult]
  stop: []
}>()
const selected = ref<TMDBSearchResult | null>(null)
watch(
  () => props.show,
  () => {
    selected.value = null
  },
)
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="批量选择版本"
    class="batch-version-modal"
    style="width: min(620px, calc(100vw - 32px))"
    :mask-closable="!loading"
    :close-on-esc="!loading"
    :closable="!loading"
    @update:show="emit('update:show', $event)"
  >
    <template v-if="group">
      <NAlert type="info" :bordered="false" class="batch-hint">
        目录「{{ group.folder_name }}」的
        {{ group.record_ids.length }} 条记录将使用同一版本。
        每个文件保留自己的季、集号；无法确认的仍留在待处理，不会统一改成同一集。
      </NAlert>
      <SearchResultList
        v-if="!selected"
        :results="group.candidates"
        :loading="loading"
        @select="selected = $event"
      />
      <div v-else class="selected-version">
        <strong>{{ selected.name }}</strong>
        <MetadataSourceBadge :item="selected" />
        <span v-if="selected.first_air_date">{{
          selected.first_air_date.slice(0, 4)
        }}</span>
        <p v-if="selected.overview">{{ selected.overview }}</p>
      </div>
    </template>
    <template #footer>
      <div v-if="loading" role="status" class="batch-hint">
        {{ progressText }}（停止会等待当前文件完成）
      </div>
      <NSpace justify="end">
        <NButton v-if="loading" @click="emit('stop')">停止后续处理</NButton>
        <NButton v-if="selected" :disabled="loading" @click="selected = null"
          >重新选择</NButton
        >
        <NButton :disabled="loading" @click="emit('update:show', false)"
          >取消</NButton
        >
        <NButton
          type="primary"
          :disabled="!selected"
          :loading="loading"
          @click="selected && emit('submit', selected)"
        >
          应用到 {{ group?.record_ids.length ?? 0 }} 条记录
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.batch-hint {
  margin-bottom: var(--space-3);
}
.selected-version {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}
.selected-version p {
  width: 100%;
  color: var(--text-2);
  margin: var(--space-2) 0;
  line-height: 1.6;
}
</style>
