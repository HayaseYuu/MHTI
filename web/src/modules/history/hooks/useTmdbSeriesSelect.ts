import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import { tmdbApi } from '@/shared/api/tmdb'
import type { TMDBSeries } from '@/shared/types/common'
import type { HistoryRecordDetail } from '@/modules/history/types'

/**
 * 季/集选择流程（ResolveConflictModal）
 *
 * 覆盖三条路径的公共状态与动作：need_selection 的 selectSeries、
 * emby 的 enterEmbySeasonSelect、手动匹配的 handleManualSelectSeries，
 * 以及各自的返回动作。错误文案逐字保留（三处不同）。
 */
export function useTmdbSeriesSelect(
  record: () => HistoryRecordDetail | null,
  /** 提交入口（手动匹配选集后） */
  onSubmit: () => Promise<void> | void,
  /**
   * 已解析的季/集。
   *
   * 仅作预选默认值：选完剧集一律进季/集步骤，用户点集卡片才提交，
   * 不再用解析值直接提交或覆盖用户选择（解析可能错，比如 OVA 被当成特别篇）。
   */
  parsedSeasonEpisode: () => { season: number; episode: number } | null,
) {
  const message = useMessage()

  const step = ref(1)
  const embyStep = ref(1)
  const manualStep = ref(1)
  const loadingSeasons = ref(false)

  const selectedTmdbId = ref<number | null>(null)
  const selectedSeriesName = ref('')
  const selectedSeason = ref<number>(1)
  const selectedEpisode = ref<number | null>(null)
  const loadedSeasons = ref<TMDBSeries['seasons']>([])
  const manualSelectedSeries = ref<TMDBSeries | null>(null)

  /** 加载季集并默认选中首个有效季（三处共用，差异经参数注入）；seed 为已解析季/集，仅作预选 */
  const loadSeasons = async (
    tmdbId: number,
    options: {
      minEpisodes?: boolean
      errorMessage: string
      seed?: { season: number; episode: number } | null
    },
  ): Promise<TMDBSeries | null> => {
    loadingSeasons.value = true
    try {
      const series = await tmdbApi.getSeries(tmdbId, record()?.advanced_settings?.r18 ?? false)
      loadedSeasons.value = series.seasons || []

      const validSeasons = options.minEpisodes
        ? loadedSeasons.value.filter((s) => s.season_number > 0 && (s.episode_count ?? 0) > 0)
        : loadedSeasons.value.filter((s) => s.season_number > 0)
      // 预选季必须在真实季列表里存在，否则退回首季且不预选集
      // （历史记录里存着解析出的第 0 季，而第 0 季已被过滤）
      const seededSeason = options.seed
        ? validSeasons.find((s) => s.season_number === options.seed?.season)
        : undefined
      const firstSeason = seededSeason ?? validSeasons[0]
      if (firstSeason) {
        selectedSeason.value = firstSeason.season_number
      }
      selectedEpisode.value = seededSeason ? options.seed?.episode ?? null : null
      return series
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string; message?: string } } }
      message.error(err.response?.data?.message || err.response?.data?.error || options.errorMessage)
      console.error(error)
      return null
    } finally {
      loadingSeasons.value = false
    }
  }

  // 选择集
  const selectEpisode = (ep: { episode_number: number }) => {
    selectedEpisode.value = ep.episode_number
  }

  // need_selection：选择剧集 → 一律进季/集步骤（已解析季/集仅作预选，用户可改）
  const selectSeries = async (result: { id: number; name: string }) => {
    selectedTmdbId.value = result.id
    selectedSeriesName.value = result.name

    const series = await loadSeasons(result.id, {
      errorMessage: '加载剧集信息失败',
      seed: parsedSeasonEpisode(),
    })
    if (series) step.value = 2
  }

  // need_selection：返回步骤1
  const goBackToStep1 = () => {
    step.value = 1
    selectedEpisode.value = null
    loadedSeasons.value = []
  }

  // Emby：进入选择季/集
  const enterEmbySeasonSelect = async () => {
    const tmdbId = record()?.conflict_data?.tmdb_id as number | null
    if (!tmdbId) {
      message.error('缺少元数据 ID')
      return
    }
    const series = await loadSeasons(tmdbId, { errorMessage: '加载剧集信息失败' })
    if (series) embyStep.value = 2
  }

  // Emby：返回步骤1
  const goBackToEmbyStep1 = () => {
    embyStep.value = 1
    selectedEpisode.value = null
    loadedSeasons.value = []
  }

  // 手动匹配：选择剧集 → 加载季信息
  const handleManualSelectSeries = async (result: { id: number }) => {
    const series = await loadSeasons(result.id, { minEpisodes: true, errorMessage: '获取剧集详情失败' })
    if (series) {
      manualSelectedSeries.value = series
      selectedTmdbId.value = result.id
      manualStep.value = 2
    }
  }

  // 手动匹配：选择季 → 进入选集
  const handleManualSelectSeason = (season: { season_number: number }) => {
    selectedSeason.value = season.season_number
    manualStep.value = 3
  }

  // 手动匹配：选择集 → 提交
  const handleManualSelectEpisode = (ep: { episode_number: number }) => {
    selectedEpisode.value = ep.episode_number
    onSubmit()
  }

  // 手动匹配：返回上一步
  const goBackManualStep = () => {
    if (manualStep.value === 2) {
      manualStep.value = 1
      manualSelectedSeries.value = null
      loadedSeasons.value = []
    } else if (manualStep.value === 3) {
      manualStep.value = 2
    }
  }

  /** 重置全部流程状态（watch(show) 内调用，顺序由父保证） */
  const reset = () => {
    step.value = 1
    embyStep.value = 1
    manualStep.value = 1
    selectedTmdbId.value = null
    selectedSeriesName.value = ''
    selectedSeason.value = 1
    selectedEpisode.value = null
    loadedSeasons.value = []
    manualSelectedSeries.value = null
  }

  return {
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
    loadSeasons,
    selectEpisode,
    selectSeries,
    goBackToStep1,
    enterEmbySeasonSelect,
    goBackToEmbyStep1,
    handleManualSelectSeries,
    handleManualSelectSeason,
    handleManualSelectEpisode,
    goBackManualStep,
    reset,
  }
}