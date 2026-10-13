import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildAiAssistSaveRequest, isAiAssistReady, mergeTaskAssistSettings } from './aiAssist.js'

const config = { enabled: false, timeout_seconds: 15, confidence_threshold: 0.9 }

test('空白 Key 不覆盖服务端密钥且模型不能随保存变更', () => {
  const request = buildAiAssistSaveRequest(config, '  ')
  assert.deepEqual(request, { ...config, api_key: null })
  assert.equal('model' in request, false)
})

test('新 Key 仅通过请求写入', () => {
  assert.equal(buildAiAssistSaveRequest(config, ' mock-not-a-real-key ').api_key, 'mock-not-a-real-key')
})

test('必须同时全局启用并配置 Key 才就绪', () => {
  for (const enabled of [false, true]) {
    for (const has_api_key of [false, true]) {
      assert.equal(isAiAssistReady({ enabled, has_api_key }), enabled && has_api_key)
    }
  }
})

test('任务开关改变后保留其它高级设置', () => {
  const settings = { download_poster: false, use_global_naming: false, r18: false, ai_assist: true }
  const changed = mergeTaskAssistSettings(settings, true, false)
  assert.deepEqual(changed, { ...settings, r18: true, ai_assist: false })
  assert.equal(settings.ai_assist, true)
})

test('高级设置确认保留任务上显式禁用 AI 的选择', () => {
  assert.equal(mergeTaskAssistSettings({ ai_assist: true }, false, false).ai_assist, false)
})
