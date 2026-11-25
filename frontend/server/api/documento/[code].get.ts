import { normalizeCode, readDocument } from '../../utils/local'

export default defineEventHandler((event) => {
  setResponseHeader(event, 'Cache-Control', 'no-store')
  const offset = Number(getQuery(event).offset ?? 0)
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100000) throw createError({ statusCode: 400, message: 'Página no válida.' })
  return readDocument(normalizeCode(getRouterParam(event, 'code')), offset)
})
