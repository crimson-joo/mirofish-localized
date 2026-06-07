import { createApp, watch } from 'vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'

const updateDocumentMeta = () => {
  const locale = i18n.global.locale.value
  document.documentElement.lang = locale
  document.title = i18n.global.t('meta.title')
  const description = document.querySelector('meta[name="description"]')
  if (description) {
    description.setAttribute('content', i18n.global.t('meta.description'))
  }
}

updateDocumentMeta()
watch(i18n.global.locale, updateDocumentMeta)

const app = createApp(App)

app.use(router)
app.use(i18n)

app.mount('#app')
