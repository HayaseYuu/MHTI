/** AI 只提供名称提示/候选择一；该许可不能绕过服务端全局启用与 Key 检查。 */
export interface AiAssistConfig {
  enabled: boolean
  model: 'deepseek-flash'
  timeout_seconds: number
  confidence_threshold: number
  has_api_key: boolean
}

export interface AiAssistSaveRequest {
  enabled: boolean
  timeout_seconds: number
  confidence_threshold: number
  api_key: string | null
}

export function buildAiAssistSaveRequest(
  config: Pick<AiAssistConfig, 'enabled' | 'timeout_seconds' | 'confidence_threshold'>,
  newKey: string,
): AiAssistSaveRequest {
  return { ...config, api_key: newKey.trim() || null }
}

export function isAiAssistReady(config: Pick<AiAssistConfig, 'enabled' | 'has_api_key'>): boolean {
  return config.enabled && config.has_api_key
}

/** 模式切换不覆盖已填写的下载、命名等高级选项。 */
export function mergeTaskAssistSettings<T extends object>(settings: T, r18: boolean, aiAssist: boolean) {
  return { ...settings, r18, ai_assist: aiAssist }
}
