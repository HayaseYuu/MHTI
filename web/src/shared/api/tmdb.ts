import api from '@/shared/api/client'
import type { TMDBSearchResponse, TMDBSeries } from '@/shared/types/common'
import { getMetadataImageUrl } from '@/shared/utils/metadata'

/**
 * TMDB 相关 API
 */
export const tmdbApi = {
  /**
   * 搜索剧集
   */
  async search(query: string, r18 = false): Promise<TMDBSearchResponse> {
    const response = await api.get<TMDBSearchResponse>('/tmdb/search', {
      params: { q: query, r18 },
    })
    return response.data
  },

  /**
   * 获取剧集详情
   */
  async getSeries(tmdbId: number, r18 = false): Promise<TMDBSeries> {
    const response = await api.get<TMDBSeries>(`/tmdb/series/${tmdbId}`, { params: { r18 } })
    return response.data
  },

  /**
   * 获取图片 URL
   */
  getImageUrl(path: string | null, size: string = 'w185'): string | null {
    return getMetadataImageUrl(path, size)
  },
}
