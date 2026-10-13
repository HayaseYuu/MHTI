<script setup lang="ts">
/**
 * TMDB 剧集搜索面板（ResolveConflictModal 的搜索弹窗）
 *
 * 纯展示：搜索状态与结果由父组件持有（NModal 会卸载内容）。
 * 模板逐字搬移自原组件的第二个 NModal（含 preset="card"、
 * style width:600px、空态文案"未找到成人内容匹配结果"）。
 */
import {
  NButton,
  NEmpty,
  NIcon,
  NImage,
  NInput,
  NList,
  NListItem,
  NModal,
  NSpace,
  NSpin,
  NTag,
  NThing,
} from 'naive-ui'
import { SearchOutline } from '@vicons/ionicons5'
import MetadataSourceBadge from '@/shared/components/business/MetadataSourceBadge.vue'
import type { TMDBSearchResult } from '@/shared/types/common'
import { useTmdbDisplay } from '@/modules/history/hooks/useTmdbDisplay'

defineProps<{
  show: boolean
  query: string
  searching: boolean
  hasSearched: boolean
  results: TMDBSearchResult[]
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'update:query': [value: string]
  search: []
  select: [result: TMDBSearchResult]
}>()

const { getImageUrl, getYear } = useTmdbDisplay()
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="搜索剧集"
    style="width: 600px; max-width: 95vw"
    :bordered="false"
    :segmented="{ content: true }"
    @update:show="emit('update:show', $event)"
  >
    <NSpace vertical>
      <NSpace>
        <NInput
          :value="query"
          placeholder="输入剧集名称搜索..."
          style="width: 400px"
          @update:value="emit('update:query', $event)"
          @keyup.enter="emit('search')"
        >
          <template #prefix><NIcon :component="SearchOutline" /></template>
        </NInput>
        <NButton type="primary" :loading="searching" @click="emit('search')">
          搜索
        </NButton>
      </NSpace>

      <NSpin :show="searching">
        <div style="min-height: 200px; max-height: 400px; overflow-y: auto">
          <NEmpty v-if="hasSearched && results.length === 0" description="未找到匹配结果" />
          <NList v-else-if="results.length > 0" hoverable clickable>
            <NListItem v-for="item in results" :key="item.id" @click="emit('select', item)">
              <NThing>
                <template #avatar>
                  <NImage
                    v-if="getImageUrl(item.poster_path, 'w92')"
                    :src="getImageUrl(item.poster_path, 'w92')!"
                    width="60"
                    height="90"
                    object-fit="cover"
                    preview-disabled
                  />
                  <div v-else class="no-poster-small">无图</div>
                </template>
                <template #header>
                  {{ item.name }}
                  <MetadataSourceBadge :item="item" />
                  <NTag v-if="item.first_air_date" size="small" style="margin-left: 8px">
                    {{ getYear(item.first_air_date) }}
                  </NTag>
                </template>
                <template #header-extra>
                  <NTag v-if="item.vote_average" type="warning" size="small">
                    {{ item.vote_average?.toFixed(1) }}
                  </NTag>
                </template>
                <template #description>
                  <div v-if="item.original_name && item.original_name !== item.name" style="color: var(--text-3); font-size: 12px">
                    {{ item.original_name }}
                  </div>
                  <div v-if="item.overview" style="font-size: 12px; color: var(--text-2); margin-top: 4px; max-height: 40px; overflow: hidden">
                    {{ item.overview }}
                  </div>
                </template>
              </NThing>
            </NListItem>
          </NList>
        </div>
      </NSpin>
    </NSpace>
  </NModal>
</template>

<style scoped>
.no-poster-small {
  width: 60px;
  height: 90px;
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--text-3);
}
</style>