import { jsonChoice, rawJson, rawJsonError, snomedJsonVersion } from '../../../utils/raw-json'

type FhirParameters = { resourceType: string, parameter: { name: string, valueString?: string, valueUri?: string, valueCode?: string }[] }

export default defineEventHandler(async (event) => {
  try {
    const id = getRouterParam(event, 'id') || ''
    if (!/^[0-9]{6,18}$/.test(id))
      throw createError({ statusCode: 400, message: 'Identificador SNOMED CT no válido.' })
    const query = getQuery(event)
    if (Object.keys(query).some(key => !['version', 'download'].includes(key)))
      throw createError({ statusCode: 400, message: 'Parámetro JSON no permitido.' })
    const version = jsonChoice(query.version, snomedJsonVersion, [snomedJsonVersion])
    const download = jsonChoice(query.download, '0', ['0', '1']) === '1'
    let data: FhirParameters
    try {
      data = await $fetch<FhirParameters>('http://127.0.0.1:8081/fhir/CodeSystem/$lookup', {
        query: { system: 'http://snomed.info/sct', version, code: id, displayLanguage: 'es', property: '*' },
        headers: { Accept: 'application/fhir+json', 'Accept-Language': 'es' }, retry: 0, timeout: 15000
      })
    } catch (error) {
      if ([400, 404].includes((error as { statusCode?: number }).statusCode ?? 0))
        throw createError({ statusCode: 404, message: 'El concepto no está disponible en esta edición SNOMED CT.' })
      throw createError({ statusCode: 503, message: 'Snowstorm no está disponible.' })
    }
    if (data.resourceType !== 'Parameters' || !Array.isArray(data.parameter))
      throw createError({ statusCode: 502, message: 'Snowstorm no devolvió una respuesta FHIR válida.' })
    const values = (name: string) => data.parameter.filter(p => p.name === name).map(p => p.valueString ?? p.valueUri ?? p.valueCode)
    if (values('version').length !== 1 || values('version')[0] !== version
      || values('code').length !== 1 || values('code')[0] !== id
      || values('system').length !== 1 || values('system')[0] !== 'http://snomed.info/sct')
      throw createError({ statusCode: 502, message: 'La respuesta no coincide con el concepto o la edición solicitados.' })
    setResponseHeader(event, 'X-JSON-Source', 'snowstorm-fhir-lookup')
    return rawJson(event, data, `snomed-${id}-${version.split('/').at(-1)}.json`, download)
  } catch (error) { return rawJsonError(event, error) }
})
