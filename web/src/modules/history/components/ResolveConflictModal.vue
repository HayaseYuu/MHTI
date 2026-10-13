<script setup lang="ts">
import { ref, computed, watch, toRef, type Ref } from 'vue'
import { NCard, NIcon, NModal, NSpace, NButton, NTag, NSpin } from 'naive-ui'
import { CloseOutline } from '@vicons/ionicons5'
import type { TMDBSearchResult, TMDBSeason } from '@/shared/types/common'
import type { HistoryRecordDetail } from '@/modules/history/types'
import TmdbSeriesSearchPanel from '@/modules/history/components/TmdbSeriesSearchPanel.vue'
import ConflictBody from '@/modules/history/components/ConflictBody.vue'
import { useConflictRecordData } from '@/modules/history/hooks/useConflictRecordData'
import { useTmdbSearch } from '@/modules/history/hooks/useTmdbSearch'
import { useTmdbSeriesSelect } from '@/modules/history/hooks/useTmdbSeriesSelect'
import { useConflictSubmit } from '@/modules/history/hooks/useConflictSubmit'
import { useConflictTitle } from '@/modules/history/hooks/useConflictTitle'
import { useRetryMatch } from '@/modules/history/hooks/useRetryMatch'

const props = defineProps<{
  show: boolean
  record: HistoryRecordDetail | null
  mode?: 'resolve' | 'retry'  // resolve=冲突处理, retry=重试刮削
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  success: []
}>()

const fileAction = ref<'overwrite' | 'skip' | 'rename'>('skip')
const embyAction = ref<'skip' | 'force' | 'change'>('force')

// 手动匹配搜索（独立实例，错误路径固定文案）
const {
  query: manualSearchQuery,
  searching: manualSearching,
  results: manualSearchResults,
  hasSearched: manualHasSearched,
  search: handleManualSearch,
  reset: resetManualSearch,
} = useTmdbSearch(
  'fixed',
  () => props.record?.advanced_settings?.r18 ?? false,
)

// 是否为重试模式
const isRetryMode = computed(() => props.mode === 'retry')

// 季/集选择流程（三路径共用，见 useTmdbSeriesSelect）
const {
  step,
  embyStep,
  manualStep,
  loadingSeasons,
  selectedTmdbId,
  selectedSeriesName,
  selectedSeason,
  selectedEpisode,
  loadedSeasons,
  manualSelectedSeries,
  selectEpisode,
  selectSeries,
  goBackToStep1,
  enterEmbySeasonSelect,
  goBackToEmbyStep1,
  handleManualSelectSeries,
  handleManualSelectSeason,
  handleManualSelectEpisode,
  goBackManualStep,
  reset: resetSeriesSelect,
} = useTmdbSeriesSelect(
  () => props.record,
  () => handleSubmit(),
  () => parsedSeasonEpisode.value,
)

// conflict_data 解析（6 个 computed，见 useConflictRecordData）
const {
  searchResults,
  parsedSeasonEpisode,
  seriesInfo,
  embyConflictInfo,
  seasons,
  currentSeasonEpisodes,
} = useConflictRecordData(toRef(props, 'record'), selectedSeason, loadedSeasons)

// 重试模式的「沿用上次匹配」与预填（见 useRetryMatch）
const { retryMatch, reset: resetRetryMatch, switchToManualSearch, prefillFromRecord } = useRetryMatch({
  record: toRef(props, 'record'),
  isRetryMode,
  selectedTmdbId,
  selectedSeason,
  selectedEpisode,
  seasons: seasons as Ref<TMDBSeason[]>,
  resetManualSearch,
})

// 标题与「是否需手动输入」（见 useConflictTitle）
const { modalTitle, needManualInput } = useConflictTitle({
  record: toRef(props, 'record'),
  isRetryMode,
  retryHasMatch: computed(() => !!retryMatch.value),
  step,
  embyStep,
  manualStep,
  selectedSeriesName,
  selectedSeason,
  manualSelectedSeriesName: () => manualSelectedSeries.value?.name,
  seriesName: () => seriesInfo.value?.name,
})

const { loading, handleSubmit } = useConflictSubmit({
  record: () => props.record,
  isRetryMode: () => isRetryMode.value,
  needManualInput: () => !!needManualInput.value,
  selectedTmdbId,
  selectedSeason,
  selectedEpisode,
  embyStep,
  fileAction,
  embyAction,
  onSuccess: () => emit('success'),
})

const {
  query: tmdbSearchQuery,
  searching: tmdbSearching,
  results: tmdbSearchResults,
  hasSearched: tmdbHasSearched,
  search: handleTmdbSearch,
  reset: resetTmdbSearch,
} = useTmdbSearch(
  'detail',
  () => props.record?.advanced_settings?.r18 ?? false,
)
const showTmdbSearchModal = ref(false)

// TMDB 搜索选择剧集
const handleTmdbSelectSeries = async (result: TMDBSearchResult) => {
  showTmdbSearchModal.value = false
  await selectSeries(result)
}

// 打开 TMDB 搜索弹窗
const openTmdbSearchModal = () => {
  resetTmdbSearch()
  showTmdbSearchModal.value = true
}

const bodyActions = {
  selectSeries,
  selectEpisode,
  backToStep1: goBackToStep1,
  searchOtherMatch: switchToManualSearch,
  enterEmbySeasonSelect,
  backToEmbyStep1: goBackToEmbyStep1,
  manualSearch: handleManualSearch,
  manualSelectSeries: handleManualSelectSeries,
  manualSelectSeason: handleManualSelectSeason,
  manualSelectEpisode: handleManualSelectEpisode,
  openSearch: openTmdbSearchModal,
}

watch(() => props.show, (show) => {
  if (show && props.record) {
    resetSeriesSelect()
    resetRetryMatch()
    fileAction.value = 'skip'
    embyAction.value = 'force'
    resetManualSearch()
    showTmdbSearchModal.value = false
    resetTmdbSearch()

    // 预填充：能沿用上次匹配就直接进确认；否则按 conflict_data / 第一季回填
    prefillFromRecord()
  }
})

const handleClose = () => {
  emit('update:show', false)
}
</script>

<template>
  <NModal
    :show="show"
    :mask-closable="false"
    transform-origin="center"
    @update:show="$emit('update:show', $event)"
  >
    <NCard class="resolve-modal" :bordered="false">
      <template #header>
        <div class="modal-header">
          <span class="title">{{ modalTitle }}</span>
          <NTag v-if="seriesInfo?.name" size="small" round>{{ seriesInfo.name }}</NTag>
        </div>
      </template>
      <template #header-extra>
        <NButton quaternary circle size="small" @click="handleClose" aria-label="关闭">
          <template #icon>
            <NIcon :component="CloseOutline" />
          </template>
        </NButton>
      </template>

      <NSpin :show="loading">
        <ConflictBody
          v-if="record"
          v-model:file-action="fileAction"
          v-model:emby-action="embyAction"
          v-model:manual-search-query="manualSearchQuery"
          v-model:selected-season="selectedSeason"
          v-model:selected-episode="selectedEpisode"
          :record="record"
          :is-retry-mode="isRetryMode"
          :retry-match="retryMatch"
          :need-manual-input="!!needManualInput"
          :step="step"
          :emby-step="embyStep"
          :manual-step="manualStep"
          :loading-seasons="loadingSeasons"
          :search-results="searchResults"
          :parsed-season-episode="parsedSeasonEpisode"
          :emby-conflict-info="embyConflictInfo"
          :seasons="seasons"
          :current-season-episodes="currentSeasonEpisodes"
          :loaded-seasons="loadedSeasons"
          :manual-searching="manualSearching"
          :manual-has-searched="manualHasSearched"
          :manual-search-results="manualSearchResults"
          :actions="bodyActions"
        />
      </NSpin>

      <template #footer>
        <NSpace justify="end">
          <!-- 重试模式返回按钮 -->
          <NButton v-if="isRetryMode && manualStep > 1" @click="goBackManualStep">
            ← 返回
          </NButton>
          <!-- 手动匹配返回按钮 -->
          <NButton v-else-if="needManualInput && manualStep > 1" @click="goBackManualStep">
            ← 返回
          </NButton>
          <NButton @click="handleClose">取消</NButton>
          <!-- 重试模式：沿用上次匹配时直接确认（搜索流程下季/集靠点卡片选择后自动提交） -->
          <NButton
            v-if="retryMatch"
            type="primary"
            :loading="loading"
            @click="handleSubmit"
          >
            开始重试
          </NButton>
          <!-- 步骤1时不显示确认按钮，用户需要点击剧集卡片 (重试模式也复用此逻辑) -->
          <NButton
            v-else-if="!(record?.conflict_type === 'need_selection' && step === 1) && !(needManualInput) && !(isRetryMode)"
            type="primary"
            :loading="loading"
            @click="handleSubmit"
          >
            确认处理
          </NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>

  <TmdbSeriesSearchPanel
    v-model:show="showTmdbSearchModal"
    :query="tmdbSearchQuery"
    :searching="tmdbSearching"
    :has-searched="tmdbHasSearched"
    :results="tmdbSearchResults"
    @update:query="tmdbSearchQuery = $event"
    @search="handleTmdbSearch"
    @select="handleTmdbSelectSeries"
  />
</template>

<style scoped>
.resolve-modal {
  width: 720px;
  max-width: 95vw;
  border-radius: 16px;
  background: var(--bg-surface);
  box-shadow: 0 20px 60px rgb(var(--black-rgb) / 15%);
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.modal-header .title {
  font-size: 18px;
  font-weight: 600;
}

.resolve-modal :deep(.n-button--primary-type) {
  box-shadow: 0 4px 12px rgb(var(--brand-rgb) / 30%);
}

.resolve-modal :deep(.n-button--primary-type:hover) {
  box-shadow: 0 6px 16px rgb(var(--brand-rgb) / 40%);
}
</style>