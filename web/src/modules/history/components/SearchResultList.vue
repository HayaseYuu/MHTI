<script setup lang="ts">
/**
 * need_selection 步骤1 的搜索结果卡片列表
 *
 * 与 TmdbSeriesSearchPanel / ManualMatchFlow 内的 NList 形态不同
 * （此处为横向 result-card 布局），故独立成组件。
 * 纯展示：结果与加载态由父组件持有。
 */
import { NIcon, NImage, NScrollbar, NSpin } from 'naive-ui'
import { ArrowBackOutline, CalendarOutline, StarOutline } from '@vicons/ionicons5'
import MetadataSourceBadge from '@/shared/components/business/MetadataSourceBadge.vue'
import type { TMDBSearchResult } from '@/shared/types/common'
import EmptyState from '@/shared/components/base/EmptyState.vue'
import { useTmdbDisplay } from '@/modules/history/hooks/useTmdbDisplay'

defineProps<{
  loading: boolean
  results: TMDBSearchResult[]
}>()

const emit = defineEmits<{
  select: [result: TMDBSearchResult]
}>()

const { getImageUrl, getYear } = useTmdbDisplay()
</script>

<template>
  <NSpin :show="loading">
    <NScrollbar style="max-height: 45vh">
      <div v-if="results.length" class="results-list">
        <div
          v-for="result in results"
          :key="result.id"
          class="result-card clickable"
          @click="emit('select', result)"
        >
          <div class="poster-wrapper">
            <NImage
              v-if="result.poster_path"
              :src="getImageUrl(result.poster_path, 'w154')!"
              object-fit="cover"
              preview-disabled
              lazy
              class="poster"
            />
            <div v-else class="no-poster">{{ result.name.charAt(0) }}</div>
          </div>
          <div class="info">
            <div class="name">{{ result.name }}</div>
            <div v-if="result.original_name && result.original_name !== result.name" class="original-name">
              {{ result.original_name }}
            </div>
            <div class="meta">
              <MetadataSourceBadge :item="result" />
              <span v-if="result.first_air_date" class="meta-item">
                <NIcon :component="CalendarOutline" :size="12" />
                {{ getYear(result.first_air_date) }}
              </span>
              <span v-if="result.vote_average" class="meta-item rating">
                <NIcon :component="StarOutline" :size="12" />
                {{ result.vote_average.toFixed(1) }}
              </span>
            </div>
            <p v-if="result.overview" class="overview">
              {{ result.overview.slice(0, 80) }}{{ result.overview.length > 80 ? '...' : '' }}
            </p>
          </div>
          <div class="arrow-hint">
            <NIcon :component="ArrowBackOutline" :size="16" style="transform: rotate(180deg)" />
          </div>
        </div>
      </div>
      <EmptyState v-else title="暂无搜索结果" description="请点击右上角搜索按钮搜索剧集" />
    </NScrollbar>
  </NSpin>
</template>

<style scoped>
.results-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px;
}

.result-card {
  display: flex;
  gap: 14px;
  padding: 12px;
  border-radius: 12px;
  background: var(--bg-subtle);
  cursor: pointer;
  transition: all 0.2s ease;
}

.result-card.clickable:hover {
  transform: translateX(4px);
  box-shadow: 0 4px 12px rgb(var(--black-rgb) / 10%);
}

.poster-wrapper {
  position: relative;
  flex-shrink: 0;
  width: 70px;
  height: 105px;
  border-radius: 8px;
  overflow: hidden;
}

.poster {
  width: 100%;
  height: 100%;
}

.no-poster {
  width: 100%;
  height: 100%;
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 600;
  color: var(--text-3);
}

.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info .original-name {
  font-size: 12px;
  color: var(--text-3);
}

.info .meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 2px;
}

.info .overview {
  margin: 0;
  margin-top: auto;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.5;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-2);
}

.meta-item.rating {
  color: var(--warning-500);
}

.arrow-hint {
  display: flex;
  align-items: center;
  color: var(--text-3);
  opacity: 0;
  transition: opacity 0.2s ease;
}

.result-card:hover .arrow-hint {
  opacity: 1;
}
</style>
