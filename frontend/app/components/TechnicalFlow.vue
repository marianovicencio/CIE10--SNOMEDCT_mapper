<script setup lang="ts">
defineProps<{ caption:string, items:{icon:string,title:string,text:string}[] }>()
</script>
<template><figure class="technical-flow"><figcaption>{{ caption }}</figcaption><ol :style="{'--steps':items.length}"><li v-for="(item,index) in items" :key="item.title"><UIcon :name="item.icon" class="tf-icon" aria-hidden="true" /><strong>{{ item.title }}</strong><p>{{ item.text }}</p><UIcon v-if="index<items.length-1" name="i-lucide-arrow-right" class="tf-arrow" aria-hidden="true" /></li></ol></figure></template>
<style scoped>
.technical-flow{margin:0;border:1px solid #333;background:#131313;border-radius:11px;padding:22px;min-width:0}.technical-flow figcaption{font-size:13px;font-weight:500;margin-bottom:20px;color:#ddd}.technical-flow ol{display:grid;grid-template-columns:repeat(var(--steps),minmax(0,1fr));gap:22px;padding:0;margin:0;list-style:none}.technical-flow li{position:relative;min-width:0;border:1px solid #333;border-radius:7px;padding:15px;background:#191919}.tf-icon{display:block;color:#aaa;font-size:19px;margin-bottom:12px}.technical-flow strong{display:block;font-size:12px;font-weight:500;line-height:1.5}.technical-flow p{font-size:11px;color:#999;line-height:1.7;margin:7px 0 0}.tf-arrow{position:absolute;right:-20px;top:50%;font-size:16px;color:#777;transform:translateY(-50%)}
@media(max-width:1000px){.technical-flow ol{grid-template-columns:1fr}.technical-flow li{padding:14px}.tf-arrow{right:calc(50% - 8px);top:auto;bottom:-20px;transform:rotate(90deg)}.technical-flow{padding:18px}}
</style>
