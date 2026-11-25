import { documentary, normalizeCode } from '../../../utils/local'
import { jsonChoice, jsonInteger, rawJson, rawJsonError } from '../../../utils/raw-json'

type DocumentaryJson = { code: string, pagination?: { next_offset: number | null } } & Record<string, unknown>

export default defineEventHandler(async (event) => {
  try {
    const code = normalizeCode(getRouterParam(event, 'code'))
    const query = getQuery(event)
    if (Object.keys(query).some(key => !['view', 'scope', 'limit', 'offset', 'download'].includes(key)))
      throw createError({ statusCode: 400, message: 'Parámetro JSON no permitido.' })
    const view = jsonChoice(query.view, 'readable', ['readable', 'evidence'])
    const scope = jsonChoice(query.scope, 'morbidity', ['all', 'morbidity', 'mortality'])
    const limit = jsonInteger(query.limit, 200, 1, 200)
    const offset = jsonInteger(query.offset, 0, 0, 100000)
    const download = jsonChoice(query.download, '0', ['0', '1']) === '1'
    let data: DocumentaryJson
    try {
      data = await $fetch<DocumentaryJson>(documentary + '/v1/codes/' + encodeURIComponent(code), {
        query: { view, scope, limit, offset }, retry: 0, timeout: 15000
      })
    } catch (error) {
      if ((error as { statusCode?: number }).statusCode === 404)
        throw createError({ statusCode: 404, message: 'El código no existe en esta edición CIE-10.' })
      throw createError({ statusCode: 503, message: 'La API CIE-10 no está disponible.' })
    }
    if (data.code !== code)
      throw createError({ statusCode: 502, message: 'La API devolvió otro código CIE-10.' })
    const next = data.pagination?.next_offset
    if (typeof next === 'number') {
      const params = new URLSearchParams({ view, scope, limit: String(limit), offset: String(next) })
      setResponseHeader(event, 'Link', `</api/raw/cie10/${code}?${params}>; rel="next"`)
    }
    setResponseHeader(event, 'X-JSON-Source', 'cie10-documentary-api')
    return rawJson(event, data, `cie10-${code}-${view}.json`, download)
  } catch (error) { return rawJsonError(event, error) }
})
