import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import { tmdbApi } from '@/shared/api/tmdb'
import type { TMDBSearchResult } from '@/shared/types/common'

/**
 * TMDB 搜索（实例化两份，用于手动匹配与搜索弹窗）
 *
 * 两处的错误路径**不同**，经 errorMode 注入，不合并：
 * - 'fixed'（手动匹配）：catch 固定文案"搜索失败"
 * - 'detail'（搜索弹窗）：解析 response.data.message/error，兜底"搜索失败"
 */
export function useTmdbSearch(errorMode: 'fixed' | 'detail' = 'fixed', r18: () => boolean = () => false) {
  const message = useMessage()

  const query = ref('')
  const searching = ref(false)
  const results = ref<TMDBSearchResult[]>([])
  const hasSearched = ref(false)

  const search = async () => {
    if (!query.value.trim()) {
      message.warning('请输入搜索关键词')
      return
    }

    searching.value = true
    hasSearched.value = true
    try {
      const response = await tmdbApi.search(query.value, r18())
      results.value = response.results
    } catch (error: unknown) {
      if (errorMode === 'detail') {
        const err = error as { response?: { data?: { error?: string; message?: string } } }
        message.error(err.response?.data?.message || err.response?.data?.error || '搜索失败')
      } else {
        message.error('搜索失败')
      }
      console.error(error)
    } finally {
      searching.value = false
    }
  }

  const reset = () => {
    query.value = ''
    results.value = []
    hasSearched.value = false
  }

  return { query, searching, results, hasSearched, search, reset }
}