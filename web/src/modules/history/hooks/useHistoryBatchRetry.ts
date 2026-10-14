import { computed, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { historyApi } from '@/modules/history/api'
import type { HistoryRecord } from '@/modules/history/types'
import {
  isBatchItemSuccess,
  runSerialBatch,
} from '@/modules/history/batchProcessing'

/** 普通刮削重试不要求已有 ID / 季 / 集，API 临时失败也可直接重新尝试。 */
export function useHistoryBatchRetry(options: {
  records: () => HistoryRecord[]
  reload: () => Promise<void> | void
  clearSelection: () => void
}) {
  const message = useMessage()
  const running = ref(false)
  const done = ref(0)
  const total = ref(0)
  const stopRequested = ref(false)
  const isSelectable = (record: HistoryRecord) =>
    ['timeout', 'failed', 'pending_action'].includes(record.status) &&
    !running.value
  const progressText = computed(() => `批量重试中 ${done.value}/${total.value}`)
  const stop = () => {
    stopRequested.value = true
  }

  const run = async (ids: string[]) => {
    if (running.value) return false
    const records = new Map(
      options.records().map((record) => [record.id, record]),
    )
    const targets = [...new Set(ids)].filter((id) => {
      const record = records.get(id)
      return record && isSelectable(record)
    })
    if (!targets.length) {
      message.warning('请选择待处理、失败或超时的记录')
      return false
    }
    running.value = true
    stopRequested.value = false
    done.value = 0
    total.value = targets.length
    try {
      const result = await runSerialBatch({
        ids: targets,
        shouldStop: () => stopRequested.value,
        execute: async (id) => {
          const response = await historyApi.retryBatch([id])
          return isBatchItemSuccess(
            response.results.find((item) => item.record_id === id),
          )
        },
        onProgress: (completed) => {
          done.value = completed
        },
        reload: options.reload,
      })
      if (result.stopped) {
        message.info(
          `已停止：完成 ${result.done}/${targets.length} 条，成功 ${result.done - result.failed} 条，未成功 ${result.failed} 条`,
        )
      } else if (result.failed) {
        message.warning(
          `批量重试完成：成功 ${result.done - result.failed} 条，${result.failed} 条仍需处理或重试`,
        )
      } else {
        message.success(`批量重试完成：${result.done} 条成功`)
      }
      return !result.stopped
    } finally {
      running.value = false
      stopRequested.value = false
      options.clearSelection()
    }
  }
  return { running, done, total, progressText, isSelectable, run, stop }
}
