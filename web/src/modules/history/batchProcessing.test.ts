import test from 'node:test'
import assert from 'node:assert/strict'
import {
  findExactBatchGroup,
  isBatchItemSuccess,
  runSerialBatch,
} from './batchProcessing.js'

test('只有真实成功终态才计成功，HTTP成功返回待处理不算', () => {
  assert.equal(isBatchItemSuccess({ success: true, status: 'success' }), true)
  assert.equal(
    isBatchItemSuccess({ success: false, status: 'pending_action' }),
    false,
  )
  assert.equal(
    isBatchItemSuccess({ success: true, status: 'pending_action' }),
    false,
  )
  assert.equal(isBatchItemSuccess(undefined), false)
})
test('统一版本必须完整覆盖一个服务端分组，不得混不同目录或孤立项', () => {
  const groups = [{ record_ids: ['a', 'b'] }, { record_ids: ['c'] }]
  assert.equal(findExactBatchGroup(groups, ['b', 'a']), groups[0])
  assert.equal(findExactBatchGroup(groups, ['a', 'c']), undefined)
  assert.equal(findExactBatchGroup(groups, ['a']), undefined)
  assert.equal(findExactBatchGroup(groups, []), undefined)
})
test('20条只处理选中的5条，包含网络异常/待处理时准确计数并继续', async () => {
  const ids = Array.from({ length: 5 }, (_, index) => String(index))
  const sent: string[] = []
  const progress: number[] = []
  const result = await runSerialBatch({
    ids,
    shouldStop: () => false,
    execute: async (id) => {
      sent.push(id)
      if (id === '1') throw new Error('API失败')
      return id !== '3'
    },
    onProgress: (done) => {
      progress.push(done)
    },
    reload: async () => {
      throw new Error('刷新失败不阻断')
    },
  })
  assert.deepEqual(sent, ids)
  assert.deepEqual(progress, [1, 2, 3, 4, 5])
  assert.deepEqual(result, { done: 5, failed: 2, stopped: false })
})
test('停止只等当前项完成，不再发送剩余记录', async () => {
  let stop = false
  const sent: string[] = []
  const result = await runSerialBatch({
    ids: ['a', 'b', 'c'],
    shouldStop: () => stop,
    execute: async (id) => {
      sent.push(id)
      stop = true
      return true
    },
    onProgress: () => {},
    reload: () => {},
  })
  assert.deepEqual(sent, ['a'])
  assert.deepEqual(result, { done: 1, failed: 0, stopped: true })
})
test('没有待处理项时不发送请求', async () => {
  const result = await runSerialBatch({
    ids: [],
    shouldStop: () => false,
    execute: async () => {
      throw new Error('不应执行')
    },
    onProgress: () => {},
    reload: () => {},
  })
  assert.deepEqual(result, { done: 0, failed: 0, stopped: false })
})
