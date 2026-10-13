/**
 * TMDB 展示辅助（ResolveConflictModal 拆分）
 *
 * getImageUrl：与原实现在本组件内的默认尺寸一致（'w300'，非 tmdbApi 的 w185），
 * 故不直接复用 tmdbApi.getImageUrl 的默认值，避免可见分辨率变化。
 * getYear：取年份前缀，缺失返回 '未知'。
 */
import { getMetadataImageUrl } from '@/shared/utils/metadata'

export function useTmdbDisplay() {
  /** TMDB 图片 URL（默认 w300，与原组件内实现一致） */
  const getImageUrl = (path: string | null, size = 'w300') => {
    return getMetadataImageUrl(path, size)
  }

  /** 从日期字符串取年份；缺失返回 '未知' */
  const getYear = (date: string | null) => {
    if (!date) return '未知'
    return date.split('-')[0]
  }

  return { getImageUrl, getYear }
}