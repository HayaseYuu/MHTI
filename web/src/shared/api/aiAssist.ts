import api from '@/shared/api/client'
import type { AiAssistConfig, AiAssistSaveRequest } from '@/shared/utils/aiAssist'

export const aiAssistApi = {
  async get(): Promise<AiAssistConfig> {
    return (await api.get<AiAssistConfig>('/config/ai-assist')).data
  },
  async save(config: AiAssistSaveRequest): Promise<AiAssistConfig> {
    return (await api.put<AiAssistConfig>('/config/ai-assist', config)).data
  },
  async deleteKey(): Promise<void> {
    await api.delete('/config/ai-assist/api-key')
  },
}
