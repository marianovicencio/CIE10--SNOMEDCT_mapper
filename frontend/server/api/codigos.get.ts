import { documentary } from '../utils/local'

export default defineEventHandler(async (event) => {
  const { prefix } = getQuery(event)
  if (typeof prefix !== 'string' || !/^[A-Z](?:[0-9]{0,2}|[0-9]{2}\.[0-9]{0,2})$/.test(prefix))
    throw createError({ statusCode: 400, message: 'Prefijo CIE-10 inválido.' })
  try {
    return await $fetch<{ items: { code: string, title: string }[] }>(documentary + '/v1/codes', {
      query: { prefix }, retry: 0, timeout: 5000
    })
  } catch {
    throw createError({ statusCode: 503, message: 'No se pudieron cargar las sugerencias CIE-10.' })
  }
})
