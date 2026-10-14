/** 批量任务必须看真实终态；HTTP 200 也可能只是再次进入待处理。 */
export function isBatchItemSuccess(
  result: { success: boolean; status: string } | undefined,
): boolean {
  return result?.success === true && result.status === 'success'
}

/** 只有服务端验证为同组、且完整覆盖所选记录，才可统一应用版本。 */
export function findExactBatchGroup<T extends { record_ids: string[] }>(
  groups: T[],
  ids: string[],
): T | undefined {
  const selected = new Set(ids)
  if (!selected.size) return undefined
  return groups.find(
    (group) =>
      group.record_ids.length === selected.size &&
      group.record_ids.every((id) => selected.has(id)),
  )
}

/** 串行、可停止：不取消当前文件整理，只在两条之间停下。刷新失败不能中断后续文件。 */
export async function runSerialBatch(options: {
  ids: string[]
  shouldStop: () => boolean
  execute: (id: string) => Promise<boolean>
  onProgress: (done: number, failed: number) => void
  reload: () => Promise<void> | void
}): Promise<{ done: number; failed: number; stopped: boolean }> {
  let done = 0
  let failed = 0
  for (const id of options.ids) {
    if (options.shouldStop()) return { done, failed, stopped: true }
    try {
      if (!(await options.execute(id))) failed += 1
    } catch {
      failed += 1
    }
    done += 1
    options.onProgress(done, failed)
    try {
      await options.reload()
    } catch {
      /* 刷新不影响本条真实结果，下次刷新会恢复 */
    }
  }
  return { done, failed, stopped: false }
}
