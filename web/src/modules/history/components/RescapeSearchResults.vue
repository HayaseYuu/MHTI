<script setup lang="ts">
/**
 * 「按 TMDB ID 重刮」弹窗的搜索结果列表
 *
 * 独立成件的原因：弹窗主体已经背着「搜索 + 手填 ID/季/集 + 提交确认」三件事，
 * 列表再留在里面就超 300 行了（见 CLAUDE.md §6 的文件长度约定）。
 *
 * 纯展示：结果与已选项由父组件持有（NModal 会卸载内容，状态不能放进来）。
 * 不用 SearchResultList.vue：那个是 need_selection 的横向卡片布局，
 * 且带悬停位移 + 投影，不符合当前设计语言（Soft Minimalism 禁项）。
 */
import { NImage, NList, NListItem, NTag } from 'naive-ui'
import MetadataSourceBadge from '@/shared/components/business/MetadataSourceBadge.vue'
import type { TMDBSearchResult } from '@/shared/types/common'
import { useTmdbDisplay } from '@/modules/history/hooks/useTmdbDisplay'

defineProps<{
  results: TMDBSearchResult[]
  /** 已选中的剧集 ID：命中时该项显示「已选」而不是 ID */
  pickedId: number | null
}>()

const emit = defineEmits<{
  select: [item: TMDBSearchResult]
}>()

const { getImageUrl, getYear } = useTmdbDisplay()
</script>

<template>
  <NList hoverable clickable>
    <NListItem v-for="item in results" :key="item.id" @click="emit('select', item)">
      <div class="result-row">
        <NImage
          v-if="getImageUrl(item.poster_path, 'w92')"
          :src="getImageUrl(item.poster_path, 'w92')!"
          width="44"
          height="66"
          object-fit="cover"
          preview-disabled
          class="result-poster"
        />
        <div v-else class="no-poster">无图</div>

        <div class="result-info">
          <div class="result-name">
            {{ item.name }}
            <MetadataSourceBadge :item="item" />
            <NTag v-if="item.first_air_date" size="small">
              {{ getYear(item.first_air_date) }}
            </NTag>
          </div>
          <div v-if="item.original_name && item.original_name !== item.name" class="result-original">
            {{ item.original_name }}
          </div>
          <div v-if="item.overview" class="result-overview">{{ item.overview }}</div>
        </div>

        <NTag v-if="pickedId === item.id" size="small" type="success">已选</NTag>

      </div>
    </NListItem>
  </NList>
</template>

<style scoped>
.result-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.result-poster {
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.no-poster {
  flex-shrink: 0;
  width: 44px;
  height: 66px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  color: var(--text-3);
  background: var(--bg-hover);
  border-radius: var(--radius-sm);
}

.result-info {
  flex: 1;
  min-width: 0;
}

.result-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  color: var(--text-1);
}

.result-original {
  font-size: var(--text-xs);
  color: var(--text-3);
}

/* 简介只做提示：限两行，避免长文本把列表拉成一张张卡片 */
.result-overview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-top: 2px;
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
  color: var(--text-2);
}

.result-id {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-3);
}
</style>
