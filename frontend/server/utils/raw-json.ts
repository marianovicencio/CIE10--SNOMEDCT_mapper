import type { H3Event } from 'h3'

export const snomedJsonVersion = 'http://snomed.info/sct/449081005/version/20261110'

export function jsonChoice(value: unknown, fallback: string, allowed: readonly string[]) {
  if (value === undefined) return fallback
  if (typeof value !== 'string' || !allowed.includes(value))
    throw createError({ statusCode: 400, message: 'Parámetro JSON no válido.' })
  return value
}

export function jsonInteger(value: unknown, fallback: number, min: number, max: number) {
  if (value === undefined) return fallback
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value))
    throw createError({ statusCode: 400, message: 'La paginación requiere números enteros.' })
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed < min || parsed > max)
    throw createError({ statusCode: 400, message: 'Paginación fuera del intervalo permitido.' })
  return parsed
}

export function rawJson(event: H3Event, data: unknown, filename?: string, download = false) {
  setResponseHeader(event, 'Content-Type', 'application/json; charset=utf-8')
  setResponseHeader(event, 'Cache-Control', 'no-store')
  setResponseHeader(event, 'X-Content-Type-Options', 'nosniff')
  if (filename) setResponseHeader(event, 'Content-Disposition', `${download ? 'attachment' : 'inline'}; filename="${filename}"`)
  return JSON.stringify(data, null, 2) + '\n'
}

export function rawJsonError(event: H3Event, error: unknown) {
  const failure = error as { statusCode?: number, message?: string }
  const known = [400, 404, 502, 503].includes(failure.statusCode ?? 0)
  const status = known ? failure.statusCode! : 503
  setResponseStatus(event, status)
  return rawJson(event, { statusCode: status, message: known ? failure.message : 'La respuesta JSON no está disponible. Intenta nuevamente.' })
}
