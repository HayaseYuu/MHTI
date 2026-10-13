<script setup lang="ts">
/**
 * 重试弹窗的「沿用上次匹配」确认面板
 *
 * 记录里已经有确定的 TMDB ID/季/集时，重试没必要再让用户搜一遍 TMDB
 * （超时记录尤其如此：匹配其实早就算出来了，只是之前没落库）。
 * 这里只展示沿用的匹配 + 输入文件，并留一个「改用其他匹配」的出口 ——
 * 匹配确实选错时仍能回到搜索流程。
 */
import { NButton } from 'naive-ui'
import type { RetryMatch } from '@/modules/history/utils'

defineProps<{
  match: RetryMatch
  /** 剧名（后端回写，旧记录可能没有） */
  title: string | null
  /** 输入文件名 */
  fileName: string
}>()

defineEmits<{
  /** 改用其他匹配：回到「搜索剧集」流程 */
  search: []
}>()
</script>

<template>
  <div class="retry-confirm">
    <dl class="match-list">
      <div class="info-line">
        <dt class="info-label">{{ match.tmdbId < 0 ? 'AniList ID' : 'TMDB ID' }}</dt>
        <dd class="info-value">{{ Math.abs(match.tmdbId) }}<span v-if="title" class="title-hint">{{ title }}</span></dd>
      </div>
      <div class="info-line">
        <dt class="info-label">季 / 集</dt>
        <dd class="info-value mono">
          S{{ String(match.season).padStart(2, '0') }}E{{ String(match.episode).padStart(2, '0') }}
        </dd>
      </div>
      <div class="info-line">
        <dt class="info-label">输入文件</dt>
        <dd class="info-value">{{ fileName }}</dd>
      </div>
    </dl>

    <p class="match-hint">
      沿用上次已确定的匹配，不再重新搜索。匹配选错时可以改用其他匹配。
    </p>

    <NButton size="small" quaternary @click="$emit('search')">改用其他匹配</NButton>
  </div>
</template>

<style scoped>
.retry-confirm {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: flex-start;
}

.match-list {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: var(--space-2) var(--space-3);
  margin: 0;
  width: 100%;
}

.info-line {
  display: contents;
}

.info-label {
  font-size: var(--text-sm);
  color: var(--text-3);
}

.info-value {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-1);
  overflow-wrap: anywhere;
}

.info-value.mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.title-hint {
  margin-left: var(--space-2);
  color: var(--text-2);
}

.match-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-3);
}
</style>
