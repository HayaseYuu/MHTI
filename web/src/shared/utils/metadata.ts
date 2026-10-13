/** 负数仅用作内部 AniList 标识，展示与外链始终使用正 ID。 */
export interface MetadataIdentity {
  id: number
  metadata_source?: 'tmdb' | 'anilist'
  anilist_id?: number | null
}

export function getMetadataSource(item: MetadataIdentity): 'tmdb' | 'anilist' {
  return item.metadata_source ?? (item.id < 0 ? 'anilist' : 'tmdb')
}

/** 主身份为 TMDB、且带 AniList 关联 ID 时，明确标记双源补全。 */
export function getMetadataSourceLabel(item: MetadataIdentity): string {
  if (getMetadataSource(item) === 'anilist') return 'AniList'
  return item.anilist_id ? 'TMDB + AniList' : 'TMDB'
}

export function getMetadataId(item: MetadataIdentity): number {
  return getMetadataSource(item) === 'anilist' ? item.anilist_id ?? Math.abs(item.id) : item.id
}

/** AniList 返回 HTTPS 绝对地址；TMDB 返回图片相对路径。 */
export function getMetadataImageUrl(path: string | null, size = 'w185'): string | null {
  if (!path || /[\s\\]/.test(path)) return null
  if (/^https:\/\//i.test(path)) {
    try {
      const url = new URL(path)
      const trustedHosts = ['image.tmdb.org', 's4.anilist.co']
      if (url.protocol !== 'https:' || !trustedHosts.includes(url.hostname)) return null
      if (url.username || url.password || url.port) return null
      return path
    } catch {
      return null
    }
  }
  // 相对图片只接受单个 / 开头的普通路径，拒绝协议相对地址及目录跳转。
  if (!/^\/[A-Za-z0-9._/-]+$/.test(path) || path.startsWith('//')) return null
  if (path.split('/').some(part => part === '.' || part === '..')) return null
  if (!/^(?:w\d+|h\d+|original)$/.test(size)) return null
  return `https://image.tmdb.org/t/p/${size}${path}`
}
