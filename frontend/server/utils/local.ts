import { resolve } from 'node:path'

export const project = resolve(process.env.MAGISTER_PROJECT_ROOT || resolve(process.cwd(), '..'))
export const documentary = 'http://127.0.0.1:8000'
export const validCode = /^[A-Z][0-9]{2}(?:\.[0-9]{1,2})?$/

export function normalizeCode(value: unknown) {
  const code = typeof value === 'string' ? value.trim().toUpperCase() : ''
  if (!validCode.test(code)) throw createError({ statusCode: 400, message: 'Ingresa un código individual, por ejemplo E10.7.' })
  return code
}

export async function readDocument(code: string, offset = 0) {
  try {
    return await $fetch(documentary + '/v1/codes/' + encodeURIComponent(code), {
      query: { scope: 'morbidity', limit: 12, offset },
      retry: 0, timeout: 12000
    })
  } catch (error) {
    const failure = error as { statusCode?: number }
    if (failure.statusCode === 404) throw createError({ statusCode: 404, message: 'El código no se encuentra en esta edición CIE-10.' })
    throw createError({ statusCode: 503, message: 'La API documental local no está disponible.' })
  }
}
