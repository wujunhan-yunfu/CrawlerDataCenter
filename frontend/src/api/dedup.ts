// 共享进行中的请求: 并发调用返回同一个 Promise, 避免同一时刻重复请求。
// 用于抵消 React StrictMode 在 dev 下对 effect 的双触发。
export function inFlight<T>(fn: () => Promise<T>): () => Promise<T> {
  let current: Promise<T> | null = null
  return () => {
    if (!current) {
      current = fn().finally(() => {
        current = null
      })
    }
    return current
  }
}