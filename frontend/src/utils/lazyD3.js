// 缓存 promise 的惰性 d3 加载：首次调用触发 import('d3') 下载，
// 之后所有调用共享同一个 promise，避免重复加载与并发重复请求。
let d3Promise = null

export function loadD3() {
  if (!d3Promise) d3Promise = import('d3')
  return d3Promise
}
