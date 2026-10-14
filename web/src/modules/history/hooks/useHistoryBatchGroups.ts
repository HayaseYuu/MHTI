import { computed, ref, watch, type Ref } from 'vue'
import { useMessage } from 'naive-ui'
import { historyApi } from '@/modules/history/api'
import type { HistoryBatchGroup, HistoryRecord } from '@/modules/history/types'
import { findExactBatchGroup } from '@/modules/history/batchProcessing'

/** 分组依据由服务端保留的作品根目录与候选交集决定，绝不仅凭同名目录混组。 */
export function useHistoryBatchGroups(options: {
  records: Ref<HistoryRecord[]>
  checkedKeys: Ref<string[]>
  running: Ref<boolean>
}) {
  const message = useMessage()
  const groups = ref<HistoryBatchGroup[]>([])
  const loading = ref(false)
  const choosing = ref(false)
  const modalGroup = ref<HistoryBatchGroup | null>(null)
  const showModal = ref(false)
  let generation = 0
  const pendingIds = computed(() =>
    options.records.value
      .filter((record) => record.status === 'pending_action')
      .map((record) => record.id),
  )
  watch(
    [() => pendingIds.value.join('\n'), options.records],
    async () => {
      const ticket = ++generation
      groups.value = []
      const ids = pendingIds.value
      if (!ids.length) {
        loading.value = false
        return
      }
      loading.value = true
      try {
        const response = await historyApi.previewBatch(ids)
        if (ticket === generation) groups.value = response.groups
      } catch {
        // 分组预览失败不阻断原有列表和单条操作，用户可点击刷新重试。
      } finally {
        if (ticket === generation) loading.value = false
      }
    },
    { immediate: true },
  )

  const selectGroup = (group: HistoryBatchGroup) => {
    if (!options.running.value)
      options.checkedKeys.value = [...group.record_ids]
  }
  const chooseVersion = async () => {
    if (choosing.value || options.running.value) return
    const ids = [...options.checkedKeys.value]
    if (!ids.length) return
    choosing.value = true
    try {
      const response = await historyApi.previewBatch(ids)
      // 预览期间用户可能改选或已启动重试，不展示过期选择。
      if (options.running.value || ids.length !== options.checkedKeys.value.length || !ids.every((id) => options.checkedKeys.value.includes(id))) return
      const group = findExactBatchGroup(response.groups, ids)
      if (!group || !group.candidates.length) {
        message.warning(
          '请选择同一作品目录、拥有共同候选版本的待处理记录，可点击上方目录快捷选择',
        )
        return
      }
      modalGroup.value = group
      showModal.value = true
    } catch {
      message.error('无法加载共同候选版本，请刷新后重试')
    } finally {
      choosing.value = false
    }
  }
  return {
    groups,
    loading,
    choosing,
    modalGroup,
    showModal,
    selectGroup,
    chooseVersion,
  }
}
