<script setup lang="ts">
type Step = { id: string, target?: string, title: string, text: string, action?: string, ready?: () => boolean }
const emit = defineEmits<{ start: [], sidebar: [open: boolean] }>()
const route = useRoute()
const active = ref(false)
const index = ref(0)
const card = useTemplateRef('card')
const heading = useTemplateRef('heading')
const storageKey = 'cie-snomed:guided-tour:v1'
const rect = ref<{left:number,top:number,width:number,height:number}|null>(null)
const viewport = ref({width:1024,height:768})
const ready = ref(true)
let previousFocus: HTMLElement | null = null
let observer: MutationObserver | undefined
let sizeObserver: ResizeObserver | undefined
let animation = 0
let timer: ReturnType<typeof setTimeout> | undefined
const visible = (selector:string) => Array.from(document.querySelectorAll<HTMLElement>(selector)).find(el=>el.getClientRects().length>0)
const selectedTab = (tab:string) => Boolean(visible(`[data-tour="tab-${tab}"][aria-pressed="true"]`))
const steps: Step[] = [
  {id:'welcome',title:'Conoce la plataforma',text:'A continuación se mostrará un tutorial de cómo utilizar la plataforma. Una vez terminado, podrás consultarlo nuevamente cuando quieras.'},
  {id:'code',target:'[data-tour="code"]',title:'1. Elige un código CIE-10',text:'Escribe la primera letra para abrir las sugerencias. Al completar el código verás el nombre de la categoría. Puedes seleccionar una sugerencia o escribir el código completo.',action:'Introduce un código completo para continuar.',ready:()=>/^[A-Z][0-9]{2}(?:\.[0-9]{1,2})?$/.test((visible('[data-tour="code"] input') as HTMLInputElement)?.value || '')},
  {id:'diagnostic',target:'[data-tour="diagnostic"]',title:'2. Añade contexto si lo tienes',text:'El diagnóstico escrito es opcional. Sirve para distinguir localización, estadio, subtipo u otros detalles. Puedes dejarlo vacío para consultar solo el alcance del código.'},
  {id:'advanced',target:'[data-tour="advanced"]',title:'3. Elige quién explica',text:'Abre Opciones avanzadas. Puedes elegir el modelo local o la API externa configurada. El modelo elegido se utilizará para generar las explicaciones. La conexión externa requiere tu autorización y utiliza saldo de API.',action:'Abre Opciones avanzadas para conocer estas opciones.',ready:()=>Boolean(visible('#consultation-options'))},
  {id:'model-options',target:'#consultation-options',title:'Opciones de explicación',text:'Aquí eliges entre el modelo local y la conexión externa. Puedes seleccionar el que prefieras o mantener la opción actual para continuar.'},
  {id:'search',target:'[data-tour="search"]',title:'4. Busca candidatos',text:'Pulsa Buscar candidatos SNOMED CT y espera los resultados. La aplicación recupera el contexto CIE-10 y busca en el catálogo SNOMED.',action:'Realiza una búsqueda. Cuando termine podrás continuar.',ready:()=>Boolean(visible('[data-tour="candidates"]'))},
  {id:'documentation',target:'[data-tour="documentation"] > .cc-document > summary',title:'5. Consulta el código de origen',text:'Consultar información CIE-10 despliega la lista tabular, el manual y el índice. Encontrarás inclusiones, exclusiones, notas y contexto recuperado de la información oficial de la versión de CIE-10 utilizada en Chile, publicada por la OMS. Puedes abrirlo ahora o revisarlo después.'},
  {id:'candidates',target:'[data-tour="candidates"] .cc-choice',title:'6. Selecciona un candidato',text:'Esta lista contiene conceptos encontrados por búsqueda textual y SAPBERT. El orden expresa relevancia de búsqueda. Las advertencias señalan diferencias que conviene revisar. Pulsa un candidato para abrir su detalle.',action:'Selecciona un candidato para continuar.',ready:()=>Boolean(visible('[data-tour="candidate-detail"]'))},
  {id:'comparison',target:'[data-tour="tab-comparison"]',title:'7. Revisa la comparación',text:'Comparación organiza la afección, la enfermedad asociada y los calificadores pertinentes, como estadio, inicio o localización. Cada punto permite abrir su respaldo documental. Aquí verás coincidencias y detalles por revisar; la explicación generada por el modelo está en otra pestaña.',action:'Abre la pestaña Comparación.',ready:()=>selectedTab('comparison')},
  {id:'explanation',target:'[data-tour="tab-explanation"]',title:'8. Pide una explicación al modelo',text:'Abre Explicación. Explicar este candidato solicita un análisis al modelo elegido. Volver a generar hace una nueva solicitud. Si una restricción bloquea la explicación o el modelo falla, se indica aquí.',action:'Abre la pestaña Explicación para ver sus controles.',ready:()=>selectedTab('explanation')},
  {id:'sources',target:'[data-tour="tab-sources"]',title:'9. Comprueba las fuentes',text:'Fuentes permite revisar los documentos y descripciones que respaldan la comparación. Tras generar una explicación, Consultar fuentes lleva a las referencias citadas por el modelo.',action:'Abre la pestaña Fuentes.',ready:()=>selectedTab('sources')},
  {id:'technical',target:'[data-tour="tab-technical"]',title:'10. Explora los datos técnicos',text:'Datos técnicos muestra el identificador SNOMED, la edición, la recuperación y el modelo utilizado. Ver JSON FHIR abre los datos SNOMED en otra pestaña. La información CIE-10 también ofrece su JSON en sus datos técnicos.',action:'Abre la pestaña Datos técnicos.',ready:()=>selectedTab('technical')},
  {id:'navigation',target:'[data-tour="navigation"]',title:'11. Recorre las secciones de la plataforma',text:'La barra lateral se organiza en tres grupos: Consulta, para buscar y revisar códigos; Proyecto, con el propósito y los desafíos del mapeo; y Documentación técnica, con el preprocesamiento, el flujo de consulta, la recuperación léxica y semántica y los modelos de explicación.'},
  {id:'repository',target:'[data-tour="repository"]',title:'12. Encuentra el proyecto en GitHub',text:'Este botón abre el repositorio público. Allí encontrarás el código de la plataforma y la guía de instalación. Si el proyecto te resulta útil, considera dale una estrella en GitHub.'},
  {id:'finish',target:'[data-tour="restart"]',title:'Todo listo para explorar',text:'Puedes repetir este recorrido con Tutorial. Las versiones de CIE-10 y SNOMED CT están al pie de la barra lateral. Para cualquier consulta, escríbeme al correo de contacto.'}
]
const step = computed(()=>steps[index.value]!)
const panelStyle = computed(()=>{
  const w=Math.min(370,viewport.value.width-24)
  const h=card.value?.offsetHeight || 300
  let left=(viewport.value.width-w)/2,top=(viewport.value.height-h)/2
  if(rect.value){
    const r=rect.value
    if(viewport.value.width>=1000 && r.left+r.width+24+w<viewport.value.width){left=r.left+r.width+18;top=r.top}
    else if(viewport.value.width>=1000 && r.left>w+24){left=r.left-w-18;top=r.top}
    else {left=Math.max(12,Math.min(r.left,viewport.value.width-w-12));top=r.top+r.height+18
      if(top+h>viewport.value.height-12)top=r.top-h-18
    }
  }
  return {width:`${w}px`,left:`${Math.max(12,left)}px`,top:`${Math.max(12,Math.min(top,viewport.value.height-h-12))}px`}
})
const masks = computed(()=>{
  const w=viewport.value.width,h=viewport.value.height,r=rect.value
  if(!r)return [{left:0,top:0,width:w,height:h}]
  return [{left:0,top:0,width:w,height:r.top},{left:0,top:r.top+r.height,width:w,height:Math.max(0,h-r.top-r.height)},{left:0,top:r.top,width:r.left,height:r.height},{left:r.left+r.width,top:r.top,width:Math.max(0,w-r.left-r.width),height:r.height}]
})
function measure(){
  if(!active.value)return
  viewport.value={width:document.documentElement.clientWidth,height:window.innerHeight}
  const element=step.value.target?visible(step.value.target):undefined
  ready.value=step.value.ready?step.value.ready():true
  if(!element){rect.value=null;return}
  let bounds=element.getBoundingClientRect()
  // Autocomplete lives in a portal; keep its options inside the interactive spotlight.
  const menu=step.value.id==='code'?visible('[role="listbox"]'):undefined
  if(menu){const m=menu.getBoundingClientRect();bounds={left:Math.min(bounds.left,m.left),top:Math.min(bounds.top,m.top),right:Math.max(bounds.right,m.right),bottom:Math.max(bounds.bottom,m.bottom)} as DOMRect}
  const left=Math.max(4,bounds.left-6),top=Math.max(4,bounds.top-6)
  rect.value={left,top,width:Math.max(0,Math.min(viewport.value.width-4,bounds.right+6)-left),height:Math.max(0,Math.min(viewport.value.height-4,bounds.bottom+6)-top)}
}
function schedule(){cancelAnimationFrame(animation);animation=requestAnimationFrame(measure)}
async function present(){
  emit('sidebar',['navigation','repository'].includes(step.value.id))
  await nextTick()
  const target=step.value.target?visible(step.value.target):undefined
  if(target?.closest('.app-sidebar'))target.scrollIntoView({block:'nearest',inline:'nearest',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})
  else if(target && !target.closest('.topbar'))window.scrollTo({top:Math.max(0,window.scrollY+target.getBoundingClientRect().top-82),behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})
  measure();heading.value?.focus({preventScroll:true})
  clearTimeout(timer);timer=setTimeout(measure,350)
}
async function start(){
  if(active.value)return
  previousFocus=document.activeElement as HTMLElement
  if(route.path!=='/')await navigateTo('/')
  emit('start');index.value=0;active.value=true
  await nextTick();await present()
}
function finish(){
  active.value=false;emit('sidebar',false)
  try{localStorage.setItem(storageKey,'seen')}catch{/* Storage may be disabled; tutorial still works. */}
  cancelAnimationFrame(animation);clearTimeout(timer)
  previousFocus?.isConnected&&previousFocus.focus({preventScroll:true})
}
function next(){if(!ready.value)return;if(index.value===steps.length-1)finish();else{index.value++;void present()}}
function back(){if(index.value>0){index.value--;void present()}}
function keyboard(event:KeyboardEvent){
  if(!active.value)return
  if(event.key==='Escape'){event.preventDefault();finish();return}
  if(event.key!=='Tab')return
  const selector='button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),summary,[tabindex="0"]'
  const target=step.value.target?visible(step.value.target):undefined
  const areas=[card.value,target,step.value.id==='code'?visible('[role="listbox"]'):undefined].filter(Boolean) as HTMLElement[]
  const items=areas.flatMap(area=>[...(area.matches(selector)?[area]:[]),...area.querySelectorAll<HTMLElement>(selector)]).filter(el=>el.getClientRects().length>0)
  if(!items.length)return
  const current=items.indexOf(document.activeElement as HTMLElement)
  if(current<0 || (!event.shiftKey&&current===items.length-1) || (event.shiftKey&&current===0)){
    event.preventDefault();items[event.shiftKey?items.length-1:0]?.focus()
  }
}
watch(active,value=>{if(import.meta.client)document.body.classList.toggle('guided-tour-active',value)})
watch(card,element=>{sizeObserver?.disconnect();if(element){sizeObserver=new ResizeObserver(schedule);sizeObserver.observe(element)}})
watch(()=>route.path,path=>{if(active.value&&path!=='/')finish()})
onMounted(()=>{
  observer=new MutationObserver(schedule)
  const page=document.querySelector('.app-main')
  if(page)observer.observe(page,{childList:true,subtree:true,attributes:true,attributeFilter:['aria-pressed','aria-expanded','open','disabled']})
  window.addEventListener('resize',schedule);window.addEventListener('scroll',schedule,true)
  window.addEventListener('input',schedule,true);window.addEventListener('click',schedule,true);window.addEventListener('keydown',keyboard,true)
  let seen=false;try{seen=localStorage.getItem(storageKey)==='seen'}catch{}
  if(!seen)timer=setTimeout(()=>void start(),400)
})
onBeforeUnmount(()=>{document.body.classList.remove('guided-tour-active');observer?.disconnect();sizeObserver?.disconnect();cancelAnimationFrame(animation);clearTimeout(timer);window.removeEventListener('resize',schedule);window.removeEventListener('scroll',schedule,true);window.removeEventListener('input',schedule,true);window.removeEventListener('click',schedule,true);window.removeEventListener('keydown',keyboard,true)})
defineExpose({start})
</script>
<template>
  <Teleport to="body">
    <div v-if="active" class="guided-tour" data-guided-tour>
      <div v-for="(mask,i) in masks" :key="i" class="gt-mask" :style="{left:mask.left+'px',top:mask.top+'px',width:mask.width+'px',height:mask.height+'px'}" aria-hidden="true" />
      <div v-if="rect" class="gt-spotlight" :style="{left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:rect.height+'px'}" aria-hidden="true" />
      <section ref="card" class="gt-card" :class="{'gt-compact':Boolean(rect)&&viewport.width<1000}" :style="panelStyle" role="dialog" aria-labelledby="guided-tour-heading" aria-describedby="guided-tour-text">
        <div class="gt-meta"><span>RECORRIDO GUIADO · {{ index+1 }} / {{ steps.length }}</span><button type="button" aria-label="Salir del tutorial" title="Salir del tutorial" @click="finish"><UIcon name="i-lucide-x" /></button></div>
        <div class="gt-progress"><span :style="{width:((index+1)/steps.length*100)+'%'}" /></div>
        <h2 id="guided-tour-heading" ref="heading" tabindex="-1">{{ step.title }}</h2>
        <p id="guided-tour-text">{{ step.text }}</p>
        <a v-if="step.id==='finish'" class="gt-email" href="mailto:mariano.vicencio@gmail.com">mariano.vicencio@gmail.com <UIcon name="i-lucide-arrow-up-right" /></a>
        <p v-if="step.action" class="gt-task" aria-live="polite"><UIcon :name="ready?'i-lucide-circle-check':'i-lucide-mouse-pointer-2'" />{{ ready?'Listo, puedes continuar.':step.action }}</p>
        <div class="gt-controls"><button type="button" class="gt-exit" @click="finish">Salir</button><div><button v-if="index>0" type="button" class="gt-back" @click="back">Atrás</button><button type="button" class="gt-next" :disabled="!ready" @click="next">{{ index===steps.length-1?'Terminar':index===0?'Comenzar':'Continuar' }}<UIcon name="i-lucide-arrow-right" /></button></div></div>
      </section>
    </div>
  </Teleport>
</template>
<style scoped>
.guided-tour{position:fixed;inset:0;z-index:1000;pointer-events:none}
.gt-mask{position:fixed;background:rgba(0,0,0,.78);pointer-events:auto}
.gt-spotlight{position:fixed;border:1px solid #e5e5e5;border-radius:10px;box-shadow:0 0 0 3px #ffffff15;pointer-events:none;transition:left .18s,top .18s,width .18s,height .18s}
.gt-card{position:fixed;pointer-events:auto;background:#191919;border:1px solid #444;border-radius:14px;padding:20px;box-shadow:0 16px 65px #0009;color:#eee;max-height:calc(100dvh - 24px);overflow:auto;font-family:inherit;animation:gt-appear .2s ease-out}
.gt-card.gt-compact{max-height:45dvh}
.gt-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#aaa;font-size:10px;letter-spacing:.09em;font-weight:500}
.gt-meta button{cursor:pointer;display:grid;place-items:center;width:28px;height:28px;border-radius:5px;font-size:16px}
.gt-meta button:hover,.gt-back:hover{background:#303030}
.gt-progress{height:2px;background:#333;margin:12px 0 20px;overflow:hidden;border-radius:2px}.gt-progress span{display:block;height:100%;background:#ddd;transition:width .2s}
.gt-card h2{margin:0 0 10px;font-size:19px;line-height:1.3;font-weight:600;letter-spacing:-.025em;outline:none}
.gt-card p{font-size:13px;line-height:1.7;color:#bcbcbc;margin:0 0 16px}
.gt-card .gt-task{display:flex;align-items:flex-start;gap:8px;padding:10px 12px;border:1px solid #3a3a3a;border-radius:7px;background:#222;color:#e0e0e0;font-size:12px}
.gt-task>span{flex:none;margin-top:3px}.gt-email{display:flex;align-items:center;gap:5px;font-size:12px;color:#eee;text-decoration:underline;text-underline-offset:3px;margin:0 0 16px;overflow-wrap:anywhere}
.gt-controls{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:20px}.gt-controls>div{display:flex;gap:6px}
.gt-controls button{font-size:12px;cursor:pointer;border-radius:6px;padding:8px 11px}.gt-exit{color:#999}.gt-back{color:#ccc}.gt-next{display:flex;align-items:center;gap:8px;background:#eee;color:#111;font-weight:600}.gt-next:disabled{opacity:.35;cursor:not-allowed}
.gt-card button:focus-visible,.gt-email:focus-visible{outline:2px solid white;outline-offset:3px}
@keyframes gt-appear{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
@media(prefers-reduced-motion:reduce){.gt-spotlight,.gt-progress span{transition:none}.gt-card{animation:none}}
@media(max-width:520px){.gt-card{padding:16px}.gt-card h2{font-size:17px}.gt-card p{font-size:12px}.gt-progress{margin:8px 0 14px}}
</style>
