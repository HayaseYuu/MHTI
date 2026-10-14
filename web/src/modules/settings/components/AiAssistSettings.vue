<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { NButton, NInput, NInputNumber, NSwitch, NTag, useDialog, useMessage } from 'naive-ui'
import SettingsSection from '@/modules/settings/components/SettingsSection.vue'
import SettingsField from '@/modules/settings/components/SettingsField.vue'
import { aiAssistApi } from '@/shared/api/aiAssist'
import { buildAiAssistSaveRequest, isAiAssistReady } from '@/shared/utils/aiAssist'
import type { AiAssistConfig } from '@/shared/utils/aiAssist'

const config = ref<AiAssistConfig>({
  enabled: false, model: 'deepseek-flash', timeout_seconds: 15,
  confidence_threshold: 0.9, has_api_key: false,
})
const keyInput = ref('')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const actionError = ref('')
const dialog = useDialog()
const message = useMessage()
const ready = computed(() => isAiAssistReady(config.value))
const canEnable = computed(() => config.value.has_api_key || !!keyInput.value.trim())

// 密钥不回填、不持久化到浏览器，不将包含请求体的异常对象写入日志。
async function load() {
  loading.value = true
  loadError.value = ''
  try {
    config.value = await aiAssistApi.get()
  } catch {
    loadError.value = '加载 AI 辅助配置失败，请重试'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value) return
  if (config.value.enabled && !canEnable.value) {
    message.warning('启用 AI 辅助需要先配置 API Key')
    return
  }
  saving.value = true
  actionError.value = ''
  try {
    config.value = await aiAssistApi.save(buildAiAssistSaveRequest({
      enabled: config.value.enabled,
      timeout_seconds: config.value.timeout_seconds,
      confidence_threshold: config.value.confidence_threshold,
    }, keyInput.value))
    keyInput.value = ''
    message.success('AI 辅助配置已保存，不会发起模型测试请求')
  } catch {
    actionError.value = '保存 AI 辅助配置失败，请检查输入或稍后重试'
  } finally {
    saving.value = false
  }
}

function confirmDelete() {
  dialog.warning({
    title: '删除 AI API Key',
    content: '删除后会同时关闭全局 AI 辅助，普通刮削不受影响。是否继续？',
    positiveText: '删除并关闭', negativeText: '取消',
    onPositiveClick: async () => {
      if (saving.value) return false
      saving.value = true
      actionError.value = ''
      try {
        await aiAssistApi.deleteKey()
        config.value.enabled = false
        config.value.has_api_key = false
        keyInput.value = ''
        message.success('API Key 已删除，AI 辅助已关闭')
      } catch {
        actionError.value = '删除 API Key 失败，请重试'
        return false
      } finally {
        saving.value = false
      }
    },
  })
}

onMounted(load)
onBeforeUnmount(() => { keyInput.value = '' })
</script>

<template>
  <SettingsSection
    title="AI 辅助刮削" description="普通刮削优先，仅在无法识别或候选有歧义时尝试 AI 兜底"
    :loading="loading" :error="loadError" :action-error="actionError" @retry="load"
  >
    <template #header-extra>
      <NTag :type="ready ? 'success' : 'default'" size="small" round>
        {{ ready ? '已启用' : '未启用' }}
      </NTag>
    </template>
    <SettingsField label="启用 AI 辅助" hint="默认关闭。启用后仍需任务允许；普通刮削成功时不会调用 AI。" width="full">
      <NSwitch v-model:value="config.enabled" :disabled="saving || (!canEnable && !config.enabled)" aria-label="全局启用 AI 辅助" />
    </SettingsField>
    <SettingsField label="模型" hint="模型固定，仅用来识别名称或从已有候选中择一。">
      <NInput value="deepseek-flash" readonly aria-label="AI 模型" />
    </SettingsField>
    <SettingsField label="API Key" hint="仅输入新 Key；留空保留已保存的 Key。保存成功后清空输入，不回显密钥。" width="full">
      <div class="key-field">
        <NInput v-model:value="keyInput" type="password" show-password-on="click"
          :disabled="saving" autocomplete="new-password" placeholder="输入 DeepSeek API Key"
          aria-label="DeepSeek API Key" />
        <span class="key-status">{{ config.has_api_key ? '已配置' : '未配置' }}</span>
      </div>
    </SettingsField>
    <SettingsField label="超时（秒）" hint="1–45 秒；超时后回到普通刮削或人工处理，不阻塞任务。">
      <NInputNumber v-model:value="config.timeout_seconds" :min="1" :max="45" :precision="0" :disabled="saving" :clearable="false" />
    </SettingsField>
    <SettingsField label="置信度阈值" hint="0.80–1.00，默认 0.90；低于阈值不自动采纳。">
      <NInputNumber v-model:value="config.confidence_threshold" :min="0.8" :max="1" :step="0.01" :precision="2" :disabled="saving" :clearable="false" />
    </SettingsField>
    <div class="assist-boundary">
      <p>AI 只辅助普通刮削：结合文件名和文件夹名识别作品，或判断现有候选中的哪一个。</p>
      <p>标题、剧情、图片及季集数据仍由普通数据源获取，AI 不能生成元数据或季集。</p>
      <p>启用后会向 DeepSeek 发送文件名、扫描根目录名、作品最外层文件夹名、最近父目录名及有限候选信息。目录上下文由后台自动获取，仅发送名称，不发送完整路径、视频、字幕或密钥内容。</p>
      <p>模型请求可能产生费用；保存配置不会调用模型。API Key 仅用于请求认证，不会写入 AI 提示。</p>
    </div>
    <template #actions>
      <NButton type="primary" :loading="saving" :disabled="loading" @click="save">保存配置</NButton>
      <NButton :disabled="!config.has_api_key || saving" @click="confirmDelete">删除 API Key</NButton>
    </template>
  </SettingsSection>
</template>

<style scoped>
.key-field { display: flex; flex-direction: column; gap: var(--space-1); width: 100%; min-width: 0; }
.key-status { font-size: var(--text-xs); color: var(--text-2); }
.assist-boundary { padding: var(--space-3); border-radius: var(--radius-md); background: var(--bg-subtle); }
.assist-boundary p { margin: 0; color: var(--text-2); font-size: var(--text-xs); line-height: var(--leading-normal); overflow-wrap: anywhere; }
.assist-boundary p + p { margin-top: var(--space-2); }
</style>
