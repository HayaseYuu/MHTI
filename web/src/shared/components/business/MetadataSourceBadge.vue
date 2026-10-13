<script setup lang="ts">
import { NTag } from 'naive-ui'
import type { MetadataIdentity } from '@/shared/utils/metadata'
import { getMetadataSource, getMetadataId, getMetadataSourceLabel } from '@/shared/utils/metadata'

defineProps<{ item: MetadataIdentity }>()
</script>

<template>
  <NTag
    size="small"
    round
    :type="getMetadataSource(item) === 'anilist' ? 'success' : 'info'"
    :title="item.anilist_id ? `AniList ID ${item.anilist_id}` : undefined"
  >
    {{ getMetadataSourceLabel(item) }} · {{ getMetadataId(item) }}
  </NTag>
</template>
