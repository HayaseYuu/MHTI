import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { historyApi } from '@/modules/history/api'
import type { HistoryRecordDetail, ScrapeLogStep } from '@/modules/history/types'
import { useWebSocket, type WSMessage } from '@/shared/composables/useWebSocket'

/**
 * 刮削记录详情（HistoryDetailPage）
 *
 * 记录加载 + WebSocket 订阅/退订 + 详情消息合并 + 断线重连恢复。
 *
 * 红线（ARCHITECTURE 避坑 #2）：useWebSocket 单例语义与 handler 的
 * 注册/注销**整体**随本 hook 搬迁，不拆分；订阅状态与消息处理保持
 * 原实现在同一处，避免注册/注销时机错配。
 */
export function useHistoryRecordDetail() {
  const route = useRoute()
  const router = useRouter()

  const loading = ref(false)
  /**
   * 加载失败信息：页面据此渲染错误态 + 重试按钮。
   * 不再用 message.error 弹一下了事 —— 弹窗消失后页面是空白，用户既看不到原因
   * 也没有重试入口（详情页的 loading / error / empty 三态必须都能落到界面上）。
   */
  const loadError = ref('')
  /** 记录被删除/查无此记录：与「加载失败」区分开，给不同的结果页与文案 */
  const notFound = ref(false)
  const record = ref<HistoryRecordDetail | null>(null)
  const realtimeLogs = ref<ScrapeLogStep[]>([])

  const { isConnected, subscribe, unsubscribe, registerHandler, unregisterHandler } = useWebSocket()

  const subscribed = ref(false)
  const recordId = computed(() => route.params.id as string)

  // 是否需要实时更新（运行中或待处理状态）
  const needsRealtime = computed(() => {
    const status = record.value?.status
    return status === 'running' || status === 'pending_action'
  })

  // 显示的日志（优先使用实时日志）
  const displayLogs = computed(() => {
    if (realtimeLogs.value.length > 0) {
      return realtimeLogs.value
    }
    return record.value?.scrape_logs || []
  })

  /** 逐字段合并 payload 到 record（原实现的字段清单，逐条保留） */
  const mergePayload = (payload: Record<string, unknown>) => {
    if (!record.value || !payload) return
    const assign = (key: keyof HistoryRecordDetail) => {
      if (payload[key] !== undefined) {
        ;(record.value as Record<string, unknown>)[key] = payload[key]
      }
    }
    const keys: (keyof HistoryRecordDetail)[] = [
      'status', 'title', 'original_title', 'season_number', 'episode_number',
      'episode_title', 'episode_overview', 'episode_air_date', 'episode_still_url',
      'poster_url', 'cover_url', 'thumb_url', 'plot', 'rating', 'votes',
      'release_date', 'tags', 'duration_seconds', 'error_message', 'folder_path',
      // 后端新增推送的字段：started_at 驱动耗时实时跳动，conflict_* 让
      // 页面在跑完前就能弹出处理入口（以前要刷新才看得到）
      'started_at', 'translator', 'conflict_type', 'conflict_data',
      'tmdb_id', 'anilist_id', 'metadata_source', 'advanced_settings',
    ]
    keys.forEach(assign)
  }

  /**
   * WebSocket 消息处理器 - 实时更新页面全部数据
   */
  const handleWSMessage = (msg: WSMessage) => {
    // 只处理当前记录的消息
    if (msg.job_id !== recordId.value) return

    const { type, payload } = msg

    switch (type) {
      case 'history_detail_update':
        mergePayload(payload)
        // 日志单独处理（数组整体替换）
        if (payload?.logs) {
          realtimeLogs.value = payload.logs
        }
        break

      case 'history_detail_log':
        // 追加或更新日志步骤
        if (payload) {
          const existingIndex = realtimeLogs.value.findIndex(s => s.name === payload.name)
          if (existingIndex >= 0) {
            realtimeLogs.value[existingIndex] = payload
          } else {
            realtimeLogs.value.push(payload)
          }
        }
        break

      case 'history_updated':
        // 历史记录更新（兼容旧消息类型）
        if (payload.id === recordId.value && record.value) {
          if (payload.status !== undefined) record.value.status = payload.status
          if (payload.title !== undefined) record.value.title = payload.title
          if (payload.season_number !== undefined) record.value.season_number = payload.season_number
          if (payload.episode_number !== undefined) record.value.episode_number = payload.episode_number
        }
        break
    }
  }

  /** 订阅当前记录的 WebSocket 更新 */
  const subscribeToRecord = () => {
    if (subscribed.value || !isConnected.value) return

    subscribe([recordId.value])
    registerHandler(handleWSMessage)
    subscribed.value = true
    console.log('[HistoryDetail] 已订阅记录:', recordId.value)
  }

  /** 取消订阅 */
  const unsubscribeFromRecord = () => {
    if (!subscribed.value) return

    unsubscribe([recordId.value])
    unregisterHandler(handleWSMessage)
    subscribed.value = false
    console.log('[HistoryDetail] 已取消订阅记录:', recordId.value)
  }

  /**
   * 取用户可读的失败原因
   *
   * 响应拦截器只 reject 原始 axios error（detail 在 response.data.detail 里），
   * 直接用 error.message 会得到「Request failed with status code 404」这种话。
   */
  const describeError = (error: unknown) => {
    const err = error as {
      response?: { status?: number; data?: { detail?: string } }
      message?: string
    }
    if (err?.response?.status === 404) {
      notFound.value = true
      return '记录不存在或已被删除'
    }
    return err?.response?.data?.detail || err?.message || '加载失败'
  }

  // 加载记录详情
  const loadRecord = async (showLoading = true) => {
    if (showLoading) loading.value = true
    loadError.value = ''
    notFound.value = false
    try {
      const newRecord = await historyApi.getRecord(recordId.value)
      record.value = newRecord

      // 如果是 running 或 pending_action 状态，订阅 WebSocket 更新
      if (newRecord.status === 'running' || newRecord.status === 'pending_action') {
        subscribeToRecord()
      } else {
        unsubscribeFromRecord()
      }
    } catch (error) {
      loadError.value = describeError(error)
      console.error(error)
    } finally {
      loading.value = false
    }
  }

  /** 重连后恢复订阅 */
  const handleReconnect = async () => {
    console.log('[HistoryDetail] WebSocket 重连，恢复订阅')
    // 重置订阅状态以便重新订阅
    subscribed.value = false
    if (needsRealtime.value) {
      subscribeToRecord()
    }
    // 刷新数据以同步状态
    await loadRecord(false)
  }

  // 监听连接状态变化，实现断线重连恢复
  watch(isConnected, async (connected, wasConnected) => {
    if (connected && !wasConnected && needsRealtime.value) {
      await handleReconnect()
    }
  })

  const goBack = () => router.push('/history')

  onMounted(loadRecord)

  onUnmounted(() => {
    unsubscribeFromRecord()
  })

  return {
    loading,
    loadError,
    notFound,
    record,
    realtimeLogs,
    isConnected,
    needsRealtime,
    displayLogs,
    loadRecord,
    goBack,
  }
}