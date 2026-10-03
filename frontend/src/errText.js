// 把 DRF 的各种错误体形（字符串 / 数组 / {detail: [...]} / {field: [...]}）
// 摊平成一段可直接展示的中文提示。
export function errText(data, fallback = '操作失败') {
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (Array.isArray(data)) return data.map(String).join('；') || fallback
  if (typeof data === 'object') {
    const parts = []
    for (const key of ['detail', 'nonFieldErrors', 'non_field_errors']) {
      const v = data[key]
      if (typeof v === 'string') parts.push(v)
      else if (Array.isArray(v)) parts.push(...v.map(String))
    }
    if (!parts.length) {
      for (const v of Object.values(data)) {
        if (typeof v === 'string') parts.push(v)
        else if (Array.isArray(v)) parts.push(...v.map(String))
      }
    }
    return parts.join('；') || fallback
  }
  return fallback
}
