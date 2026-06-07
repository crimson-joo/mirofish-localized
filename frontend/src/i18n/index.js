import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const DEFAULT_LOCALE = 'ko'
const messages = {}
const availableLocales = []

for (const path in localeFiles) {
  const key = path.match(/\/([^/]+)\.json$/)[1]
  if (languages[key]) {
    messages[key] = localeFiles[path].default
  }
}

for (const key of Object.keys(languages)) {
  if (messages[key]) {
    availableLocales.push({ key, label: languages[key].label })
  }
}

const savedLocale = messages[localStorage.getItem('locale')] ? localStorage.getItem('locale') : DEFAULT_LOCALE

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'ko',
  messages
})

export { availableLocales }
export default i18n
