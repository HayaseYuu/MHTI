<script setup lang="ts">
/**
 * TMDB 认证状态行（TmdbTokenCard 顶部）
 *
 * 原先是一个自带成功/失败/警告三套彩色底 + 44px 彩色图标块 + 圆角胶囊标签的大卡片：
 * 状态语义已经由 StatusBadge（点 + 文字）表达，再铺一层底色只是重复强调，暗色下还刺眼。
 * 现在只有一行：Token 状态徽章 + R18 徽章 + 上次检测时间 + 原因（有则显示），操作按钮靠右。
 *
 * R18 徽章不可省：Token 有效不等于能看到成人内容——TMDB 账户在官网隐藏了成人内容时，
 * R18 任务会返回 0 条结果并报「未找到匹配的成人剧集」，看上去像关键词不对。
 */
import { NButton, NIcon } from 'naive-ui'
import { KeyOutline, RefreshOutline, TimeOutline, TrashOutline } from '@vicons/ionicons5'
import type { ApiTokenStatus } from '@/shared/types/common'
import StatusBadge from '@/shared/components/business/StatusBadge.vue'

/** 徽章色调（与 StatusBadge 的 BadgeStatus 一致，这里只用到这几种） */
type BadgeTone = 'success' | 'warning' | 'error' | 'info' | 'pending' | 'default'

defineProps<{
  status: ApiTokenStatus | null
  statusConfig: { status: BadgeTone; text: string }
  adultConfig: { status: BadgeTone; text: string }
  tokenLoading: boolean
  verifyTime: string | null
}>()

const emit = defineEmits<{
  revalidate: []
  delete: []
  'open-wizard': []
}>()
</script>

<template>
  <div class="tmdb-status">
    <div class="status-info">
      <StatusBadge :status="statusConfig.status" :text="statusConfig.text" />
      <StatusBadge
        v-if="status?.is_configured"
        :status="adultConfig.status"
        :text="adultConfig.text"
      />
      <span v-if="status?.adult_checked_at" class="status-meta">
        <NIcon :component="TimeOutline" :size="14" />
        上次检测 {{ verifyTime }}
      </span>
    </div>

    <p v-if="status?.error_message" class="status-error">{{ status.error_message }}</p>

    <!-- R18 未开启/无法判定时才展开原因：已开启时这句是冗余 -->
    <p
      v-if="status?.is_configured && status.adult_enabled !== true && status.adult_message"
      class="status-adult"
      :class="{ 'is-off': status.adult_enabled === false }"
    >
      R18 任务提示：{{ status.adult_message }}
      <span v-if="status.adult_enabled === false">（表番模式不受此限制。）</span>
    </p>

    <div class="status-actions">
      <template v-if="status?.is_configured">
        <NButton size="small" :loading="tokenLoading" @click="emit('revalidate')">
          <template #icon>
            <NIcon :component="RefreshOutline" />
          </template>
          重新检测
        </NButton>
        <NButton size="small" @click="emit('delete')">
          <template #icon>
            <NIcon :component="TrashOutline" />
          </template>
          删除
        </NButton>
      </template>
      <NButton type="primary" size="small" @click="emit('open-wizard')">
        <template #icon>
          <NIcon :component="KeyOutline" />
        </template>
        {{ status?.is_configured ? '重新配置' : '配置向导' }}
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.tmdb-status {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.status-info {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.status-meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-2);
}

.status-error {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--danger-500);
  overflow-wrap: anywhere;
}

/* R18 原因：未开启用警告色，无法判定用次要文本色（不是错误，只是没结论） */
.status-adult {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--text-2);
  overflow-wrap: anywhere;
}

.status-adult.is-off {
  color: var(--warning-500);
}

.status-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

@media (max-width: 640px) {
  .status-actions :deep(.n-button) {
    flex: 1 1 auto;
  }
}
</style>
