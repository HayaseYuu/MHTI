import { computed, ref, type Ref } from 'vue'
import type { HistoryRecord } from '@/modules/history/types'
import { useHistoryBatchRetry } from '@/modules/history/hooks/useHistoryBatchRetry'

/**
 * 列表页多选 + 批量重试（HistoryPage 装配用）
 *
 * 从页面里抽出：勾选态、可勾选判定、进度文案都是批量重试的局部状态，
 * 页面只需要接线到工具栏与表格/卡片。翻页或换筛选时选中集合会失效，
 * 由调用方在对应的 watch 里调 clear()（批量运行中的刷新不算，否则进度条会中途消失）。
 */
export function useHistorySelection(options: {
  records: Ref<HistoryRecord[]>
  reload: () => Promise<void> | void
}) {
  const checkedKeys = ref<string[]>([])

  const clear = () => {
    checkedKeys.value = []
  }

  const {
    running,
    done,
    total,
    isSelectable,
    run,
    stop,
  } = useHistoryBatchRetry({
    records: () => options.records.value,
    reload: options.reload,
    clearSelection: clear,
  })

  /** 移动卡片勾选：卡片只知道自己的 id，集合在页面这层维护 */
  const toggle = (record: HistoryRecord, value: boolean) => {
    if (running.value) return
    if (value) {
      if (!isSelectable(record)) return
      if (!checkedKeys.value.includes(record.id)) checkedKeys.value = [...checkedKeys.value, record.id]
    } else {
      checkedKeys.value = checkedKeys.value.filter((id) => id !== record.id)
    }
  }

  const percent = computed(() => (total.value === 0 ? 0 : Math.round((done.value / total.value) * 100)))
  const progressText = computed(() => `批量重试中 ${done.value}/${total.value}`)

  return {
    checkedKeys,
    running,
    percent,
    progressText,
    isSelectable,
    clear,
    toggle,
    run: () => run(checkedKeys.value),
    stop,
  }
}
