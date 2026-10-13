<script setup lang="ts">
/**
 * 手动匹配三步流程（搜索 → 选季 → 选集）
 *
 * 合并原组件中逐字重复的两处：retry 模式与 needManualInput（no_match /
 * search_failed / api_failed）分支——两处唯一差异是搜索空态文案，经
 * emptyDescription 注入（retry 传"未找到匹配结果"，手动传默认值）。
 *
 * 纯展示：步骤状态与数据由父组件持有，本组件只 emit 交互。
 */
import {
  NButton,
  NEmpty,
  NImage,
  NInput,
  NList,
  NListItem,
  NSpace,
  NSpin,
  NTag,
  NThing,
} from 'naive-ui'
import MetadataSourceBadge from '@/shared/components/business/MetadataSourceBadge.vue'
import type { TMDBEpisode, TMDBSearchResult, TMDBSeason } from '@/shared/types/common'
import { useTmdbDisplay } from '@/modules/history/hooks/useTmdbDisplay'

withDefaults(defineProps<{
  step: number
  searchQuery: string
  searching: boolean
  hasSearched: boolean
  results: TMDBSearchResult[]
  validSeasons: TMDBSeason[]
  currentEpisodes: TMDBEpisode[]
  /** 搜索空态文案（retry 与手动匹配措辞不同） */
  emptyDescription?: string
}>(), {
  emptyDescription: '未找到成人内容匹配结果',
})

const emit = defineEmits<{
  'update:searchQuery': [value: string]
  search: []
  'select-series': [item: TMDBSearchResult]
  'select-season': [season: TMDBSeason]
  'select-episode': [ep: TMDBEpisode]
}>()

const { getImageUrl, getYear } = useTmdbDisplay()
</script>

<template>
  <div>
    <!-- 步骤 1: 搜索 -->
    <template v-if="step === 1">
      <NSpace>
        <NInput
          :value="searchQuery"
          placeholder="输入剧集名称搜索..."
          style="width: 450px"
          @update:value="emit('update:searchQuery', $event)"
          @keyup.enter="emit('search')"
        />
        <NButton type="primary" :loading="searching" @click="emit('search')">
          搜索
        </NButton>
      </NSpace>

      <NSpin :show="searching">
        <div style="min-height: 200px; max-height: 400px; overflow-y: auto">
          <NEmpty v-if="hasSearched && results.length === 0" :description="emptyDescription" />
          <NList v-else-if="results.length > 0" hoverable clickable>
            <NListItem v-for="item in results" :key="item.id" @click="emit('select-series', item)">
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
    </template>

    <!-- 步骤 2: 选择季 -->
    <template v-else-if="step === 2">
      <div style="min-height: 200px; max-height: 350px; overflow-y: auto">
        <NEmpty v-if="validSeasons.length === 0" description="暂无可用季" />
        <NList v-else hoverable clickable>
          <NListItem v-for="season in validSeasons" :key="season.season_number" @click="emit('select-season', season)">
            <NThing>
              <template #avatar>
                <NImage
                  v-if="getImageUrl(season.poster_path, 'w92')"
                  :src="getImageUrl(season.poster_path, 'w92')!"
                  width="60"
                  height="90"
                  object-fit="cover"
                  preview-disabled
                />
                <div v-else class="no-poster-small">S{{ season.season_number }}</div>
              </template>
              <template #header>
                {{ season.name || `第${season.season_number}季` }}
                <NTag size="small" style="margin-left: 8px">
                  {{ season.episode_count }} 集
                </NTag>
              </template>
              <template #description>
                <div v-if="season.air_date" style="font-size: 12px; color: var(--text-3)">
                  首播: {{ season.air_date }}
                </div>
              </template>
            </NThing>
          </NListItem>
        </NList>
      </div>
    </template>

    <!-- 步骤 3: 选择集 -->
    <template v-else-if="step === 3">
      <div style="min-height: 200px; max-height: 350px; overflow-y: auto">
        <NEmpty v-if="currentEpisodes.length === 0" description="暂无集信息" />
        <NList v-else hoverable clickable>
          <NListItem v-for="ep in currentEpisodes" :key="ep.episode_number" @click="emit('select-episode', ep)">
            <NThing>
              <template #avatar>
                <NImage
                  v-if="getImageUrl(ep.still_path, 'w185')"
                  :src="getImageUrl(ep.still_path, 'w185')!"
                  width="120"
                  height="68"
                  object-fit="cover"
                  preview-disabled
                />
                <div v-else class="no-still">E{{ ep.episode_number }}</div>
              </template>
              <template #header>
                第{{ ep.episode_number }}集 - {{ ep.name || '未命名' }}
              </template>
              <template #header-extra>
                <NTag v-if="ep.vote_average" type="warning" size="small">
                  {{ ep.vote_average?.toFixed(1) }}
                </NTag>
              </template>
              <template #description>
                <div v-if="ep.air_date" style="font-size: 12px; color: var(--text-3)">
                  播出: {{ ep.air_date }}
                </div>
              </template>
            </NThing>
          </NListItem>
        </NList>
      </div>
    </template>
  </div>
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

/* no-still：复刻原文件同名双定义中的胜出版（后者，深色渐变网格样式）——
   第一处 120×68 列表版被同名覆盖失效，故此处只保留生效版本，零视觉变化 */
.no-still {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: bold;
  color: var(--text-2);
  background: var(--bg-hover);
}
</style>