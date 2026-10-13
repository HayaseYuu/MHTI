import { ref, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { configApi } from '@/shared/api/config'
import type { ApiTokenStatus } from '@/shared/types/common'
import { describeError } from '@/modules/settings/hooks/useSettingsForm'

/** 徽章色调（StatusBadge 用）：状态语义只靠它表达，不再在 hook 里散颜色值 */
type BadgeTone = 'success' | 'warning' | 'error' | 'info' | 'pending' | 'default'

/**
 * TMDB API Token 状态机（SystemSettings）
 *
 * 加载/保存/重新检测/删除 Token、状态呈现配置、R18 探测结论、时间格式化；
 * TmdbSetupWizard 的显示开关同在此处托管。
 *
 * 「重新检测」走后端 POST /config/api-token/verify：远端重验 Token 并重探 R18，
 * 而不是重新读一遍库里的旧状态。
 * 状态配置只给「色调 + 文案」，颜色交给 StatusBadge 的令牌类（原先 hook 里带 color
 * 字段，等于把颜色写在逻辑层，暗色模式只能靠调用方自觉）。
 */
export function useTmdbToken() {
  const message = useMessage()

  const tokenLoading = ref(false)
  const tokenSaving = ref(false)
  const tokenInput = ref('')
  const tokenStatus = ref<ApiTokenStatus | null>(null)
  const tokenError = ref('')
  const showWizard = ref(false)

  // Token 状态配置：色调 + 文案
  const statusConfig = computed<{ status: BadgeTone; text: string }>(() => {
    if (!tokenStatus.value) return { status: 'default', text: '加载中…' }
    if (tokenStatus.value.is_configured && tokenStatus.value.is_valid) {
      return { status: 'success', text: '已配置且有效' }
    }
    if (tokenStatus.value.is_configured && tokenStatus.value.is_valid === false) {
      return { status: 'error', text: '配置无效' }
    }
    if (tokenStatus.value.is_configured) {
      return { status: 'warning', text: '已配置但未验证' }
    }
    return { status: 'default', text: '未配置' }
  })

  // 格式化时间
  const formatVerifyTime = (time: string | null) => {
    if (!time) return null
    const date = new Date(time)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  /**
   * R18（成人内容）探测结论的展示配置
   *
   * 它不由 Token 是否有效推导：Token 有效但账户在官网隐藏了成人内容时，刮削会召回
   * 0 条结果且报「未找到匹配的成人剧集」，看起来像搜不到而不是没权限。
   */
  const adultConfig = computed<{ status: BadgeTone; text: string }>(() => {
    const status = tokenStatus.value
    if (!status || !status.is_configured) return { status: 'default', text: 'R18 未检测' }
    if (status.adult_enabled === true) return { status: 'success', text: 'R18 已开启' }
    if (status.adult_enabled === false) return { status: 'warning', text: 'R18 未开启' }
    return { status: 'default', text: 'R18 未检测' }
  })

  // 加载 Token 状态
  const loadTokenStatus = async () => {
    tokenLoading.value = true
    tokenError.value = ''
    try {
      tokenStatus.value = await configApi.getApiTokenStatus()
    } catch (error) {
      // 读不到状态时仍然放行配置向导，只在分组顶部挂一条提示
      tokenError.value = describeError(error, 'TMDB 状态读取失败')
      console.error(error)
    } finally {
      tokenLoading.value = false
    }
  }

  // 保存 Token
  const saveToken = async () => {
    if (!tokenInput.value.trim()) {
      message.warning('请输入 API Token')
      return
    }
    tokenSaving.value = true
    try {
      const response = await configApi.saveApiToken(tokenInput.value.trim())
      if (response.success) {
        message.success(response.message)
        tokenStatus.value = response.status
        tokenInput.value = ''
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error('保存失败')
      console.error(error)
    } finally {
      tokenSaving.value = false
    }
  }

  /**
   * 重新检测：远端重验 Token + 重探 R18
   *
   * 原先只是重新读一遍状态接口（后端不验证），所以 Token 在 TMDB 那边被删掉后页面
   * 依旧显示「已配置且有效」；现在走后端 /api-token/verify 真实重验。
   */
  const revalidateToken = async () => {
    if (!tokenStatus.value?.is_configured) return

    tokenLoading.value = true
    try {
      tokenStatus.value = await configApi.verifyApiToken()
      if (tokenStatus.value.is_valid) {
        message.success('Token 验证通过')
      } else {
        message.error(tokenStatus.value.error_message || 'Token 验证失败')
      }
      if (tokenStatus.value.is_valid && tokenStatus.value.adult_enabled === false) {
        message.warning('TMDB 账户未开启 R18 内容，仅影响成人剧集任务，表番模式不受此限制')
      }
    } catch (error) {
      message.error('验证失败')
      console.error(error)
    } finally {
      tokenLoading.value = false
    }
  }

  // 删除 Token
  const deleteToken = async () => {
    try {
      const response = await configApi.deleteApiToken()
      if (response.success) {
        message.success(response.message)
        tokenStatus.value = {
        is_configured: false,
        is_valid: null,
        last_verified: null,
        error_message: null,
        adult_enabled: null,
        adult_message: null,
        adult_checked_at: null,
      }
      } else {
        message.warning(response.message)
      }
    } catch (error) {
      message.error('删除失败')
      console.error(error)
    }
  }

  // 向导成功回调
  const handleWizardSuccess = () => {
    loadTokenStatus()
  }

  return {
    tokenLoading,
    tokenSaving,
    tokenInput,
    tokenStatus,
    tokenError,
    showWizard,
    statusConfig,
    adultConfig,
    formatVerifyTime,
    loadTokenStatus,
    saveToken,
    revalidateToken,
    deleteToken,
    handleWizardSuccess,
  }
}
