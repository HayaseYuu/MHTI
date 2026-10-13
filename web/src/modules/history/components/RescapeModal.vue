<script setup lang="ts">
/**
 * 「按 TMDB ID 重刮」弹窗（列表页行操作 / 详情页头操作共用）
 *
 * 为什么从内联 popover 改成弹窗（用户要求）：
 * - 匹配错的时候用户手里通常没有正确的 ID，得先搜 TMDB 再拿 ID；内联浮层没有
 *   放搜索结果的位置，只能靠用户自己去别处抄 ID；
 * - 弹窗同时承担二次确认：后端允许对已成功的记录重刮，代价是可能产生重复产物，
 *   这句话要写在提交按钮旁边，不能藏在浮层里。
 *
 * 交互约定：
 * - 搜索 → 点击结果把该剧集 ID 填入输入框，并显示已选剧集名（避免填错）；
 * - 季/集默认取记录里已存的值，仍可手改；
 * - 本组件只 emit payload，真正的请求由页面发起（与 popover 时期一致）。
 */
import { computed, ref, watch } from 'vue'
import {
  NButton,
  NEmpty,
  NIcon,
  NInput,
  NModal,
  NScrollbar,
  NSelect,
  NSpace,
  NSpin,
} from 'naive-ui'
import { SearchOutline } from '@vicons/ionicons5'
import type { HistoryRecord } from '@/modules/history/types'
import type { TMDBSearchResult } from '@/shared/types/common'
import { useTmdbSearch } from '@/modules/history/hooks/useTmdbSearch'
import { getMetadataId, getMetadataSource } from '@/shared/utils/metadata'
import RescapeSearchResults from '@/modules/history/components/RescapeSearchResults.vue'

const props = defineProps<{
  show: boolean
  record: HistoryRecord | null
  /** 提交中：禁用按钮并提示进度 */
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [payload: { tmdbId: number; season: number; episode: number }]
}>()

const { query, searching, results, hasSearched, search, reset } = useTmdbSearch(
  'detail',
  () => props.record?.advanced_settings?.r18 ?? false,
)

const tmdbId = ref('')
const metadataSource = ref<'tmdb' | 'anilist'>('tmdb')
const r18 = computed(() => props.record?.advanced_settings?.r18 ?? false)
const sourceOptions = computed(() => [
  { label: 'TMDB', value: 'tmdb' },
  ...(!r18.value ? [{ label: 'AniList', value: 'anilist' }] : []),
])
const season = ref('1')
const episode = ref('1')
const picked = ref<TMDBSearchResult | null>(null)

// 每次打开都从记录重新取值：上一次输入不应残留（否则容易把别的记录的 ID 提交上去）
watch(() => props.show, (show) => {
  if (!show) return
  reset()
  picked.value = null
  metadataSource.value = 'tmdb'
  tmdbId.value = ''
  season.value = String(props.record?.season_number ?? 1)
  episode.value = String(props.record?.episode_number ?? 1)
})

function parse(text: string): number | null {
  const value = Number(text.trim())
  return Number.isInteger(value) && value >= 0 ? value : null
}

const parsedId = computed(() => parse(tmdbId.value))
const parsedSeason = computed(() => parse(season.value))
const parsedEpisode = computed(() => parse(episode.value))
const valid = computed(
  () =>
    parsedId.value !== null && parsedId.value > 0 &&
    parsedSeason.value !== null &&
    parsedEpisode.value !== null
)

/** 记录行摘要：确认弹窗里的操作对象与表格里点的那一行是同一条 */
const recordSummary = computed(() => {
  const record = props.record
  if (!record) return ''
  const parts: string[] = [`#${record.display_id}`]
  if (record.title) parts.push(record.title)
  const episode: string[] = []
  if (record.season_number != null) episode.push(`S${String(record.season_number).padStart(2, '0')}`)
  if (record.episode_number != null) episode.push(`E${String(record.episode_number).padStart(2, '0')}`)
  if (episode.length) parts.push(episode.join(''))
  return parts.join(' · ')
})

function handlePick(item: TMDBSearchResult) {
  picked.value = item
  metadataSource.value = getMetadataSource(item)
  tmdbId.value = String(getMetadataId(item))
}

function handleClose() {
  emit('update:show', false)
}

function handleSubmit() {
  if (!valid.value || props.loading) return
  emit('submit', {
    tmdbId: metadataSource.value === 'anilist' ? -(parsedId.value as number) : parsedId.value as number,
    season: parsedSeason.value as number,
    episode: parsedEpisode.value as number,
  })
  emit('update:show', false)
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="按元数据 ID 重刮"
    style="width: 640px; max-width: 95vw"
    :bordered="false"
    :segmented="{ content: true }"
    @update:show="emit('update:show', $event)"
  >
    <NSpace vertical :size="16">
      <p v-if="recordSummary" class="record-summary">{{ recordSummary }}</p>

      <!-- 搜索：给「不知道正确 ID」的场景一条出路 -->
      <NSpace>
        <NInput
          v-model:value="query"
          :placeholder="r18 ? '输入成人剧集名称搜索 TMDB...' : '输入表番名称搜索 TMDB + AniList...'"
          :input-props="{ 'aria-label': '搜索剧集名称' }"
          @keyup.enter="search"
        >
          <template #prefix><NIcon :component="SearchOutline" /></template>
        </NInput>
        <NButton type="primary" :loading="searching" @click="search">搜索</NButton>
      </NSpace>

      <NSpin :show="searching">
        <NScrollbar style="max-height: 260px">
          <NEmpty v-if="hasSearched && results.length === 0" description="未找到匹配结果" />
          <RescapeSearchResults
            v-else-if="results.length > 0"
            :results="results"
            :picked-id="picked?.id ?? null"
            @select="handlePick"
          />
        </NScrollbar>
      </NSpin>

      <div class="fields">
        <label class="field field-source">
          <span class="field-label">数据源</span>
          <NSelect v-model:value="metadataSource" :options="sourceOptions" aria-label="元数据来源" />
        </label>
        <label class="field">
          <span class="field-label">{{ metadataSource === 'anilist' ? 'AniList ID' : 'TMDB ID' }}</span>
          <NInput
            v-model:value="tmdbId"
            placeholder="例如 12345"
            :input-props="{ inputmode: 'numeric', 'aria-label': '元数据 ID' }"
          />
        </label>
        <label class="field field-narrow">
          <span class="field-label">季</span>
          <NInput
            v-model:value="season"
            :input-props="{ inputmode: 'numeric', 'aria-label': '季号' }"
          />
        </label>
        <label class="field field-narrow">
          <span class="field-label">集</span>
          <NInput
            v-model:value="episode"
            :input-props="{ inputmode: 'numeric', 'aria-label': '集号' }"
          />
        </label>
      </div>

      <p v-if="picked" class="picked-hint">
        已选：{{ picked.name }}（{{ getMetadataSource(picked) === 'anilist' ? 'AniList' : 'TMDB' }} ID {{ getMetadataId(picked) }}），提交前请确认季/集是否与该剧集一致。
      </p>

      <p class="hint">
        会用该 ID 重新刮削并写入元数据，可能新增或覆盖已整理的文件。
      </p>
    </NSpace>

    <template #footer>
      <NSpace justify="end">
        <NButton @click="handleClose">取消</NButton>
        <NButton type="primary" :disabled="!valid" :loading="loading" @click="handleSubmit">
          开始重刮
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.record-summary {
  font-size: var(--text-sm);
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fields {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.field {
  flex: 1 1 110px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.field-source {
  flex: 0 0 108px;
}

.field-narrow {
  flex: 0 0 88px;
}

.field-label {
  font-size: var(--text-xs);
  color: var(--text-2);
}

.picked-hint {
  font-size: var(--text-sm);
  color: var(--text-1);
}

.hint {
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--text-3);
}
</style>
