import 'core-js/stable' // to polyfill ECMAScript features
import 'regenerator-runtime/runtime' // to use transpiled generator functions
import '@mdi/font/css/materialdesignicons.min.css' // ensure you are using css-loader
import Vue from 'vue'
import Vuetify from 'vuetify'
import 'vuetify/dist/vuetify.min.css'
import Vuelidate from 'vuelidate'
import Vue2Filters from 'vue2-filters'
import Affix from 'vue-affix'
import configHelper from '@/utils/config-helper'
import router from '@/router'
import store from '@/store/store'
import { withFlagProvider } from 'ld-vue'
import '@/registerServiceWorker'
import '@/assets/styles/base.scss'
import '@/assets/styles/layout.scss'
import '@/assets/styles/overrides.scss'
import TokenServices from 'sbc-common-components/src/services/token.services'
import App from '@/App.vue'

// get rid of "You are running Vue in development mode" console message
Vue.config.productionTip = false

Vue.use(Vuetify)
Vue.use(Vuelidate)
Vue.use(Vue2Filters)
Vue.use(Affix)

const vuetify = new Vuetify({ iconfont: 'mdi' })

/**
 * first fetch config from server, then load Vue
 */
configHelper.fetchConfig()
  .then(() => {
    // ensure we have the necessary Keycloak tokens
    if (!haveKcTokens()) {
      resetAuth(() => {})
      if (!haveKcTokens()) {
        console.info('Redirecting to Auth URL...')
        const authUrl = sessionStorage.getItem('AUTH_URL')
        // assume Auth URL is always reachable
        window.location.assign(authUrl)
        return // do not execute remaining code
      }
    }

    // start token service to refresh KC token periodically
    console.info('Starting token refresh service...')
    const tokenServices = new TokenServices()
    tokenServices.initUsingUrl(sessionStorage.getItem('KEYCLOAK_CONFIG_URL'))
      .then(() => tokenServices.scheduleRefreshTimer())
      .catch(err => console.error(err))

    new Vue({
      vuetify,
      router,
      store,
      mixins: [withFlagProvider({ clientSideId: window['ldClientId'] })],
      render: h => h(App)
    }).$mount('#app')
  })
  .catch(error => {
    console.error('Error fetching config -', error)
    alert('Fatal error loading app')
  })

function haveKcTokens (): boolean {
  return Boolean(sessionStorage.getItem('KEYCLOAK_TOKEN') &&
    sessionStorage.getItem('KEYCLOAK_REFRESH_TOKEN') &&
    sessionStorage.getItem('KEYCLOAK_ID_TOKEN'))
}

function resetAuth (func) {
  var xhr = new XMLHttpRequest()
  xhr.open('POST', 'https://auth-api-dev.pathfinder.gov.bc.ca/api/v1/token', false)
  xhr.setRequestHeader('Content-Type', 'application/json;charset=UTF-8')
  xhr.onload = function () {
    // do something to response
    var data = JSON.parse(this.responseText)
    if (data && data.access_token) {
      sessionStorage['KEYCLOAK_TOKEN'] = data['access_token']
      sessionStorage['KEYCLOAK_REFRESH_TOKEN'] = data['refresh_token']
      sessionStorage['KEYCLOAK_ID_TOKEN'] = data['access_token']
      sessionStorage['ID_TOKEN'] = data['access_token']
      // sessionStorage['BUSINESS_IDENTIFIER'] = 'BC0000294'
      sessionStorage['BUSINESS_IDENTIFIER'] = 'CP0001184'
    } else {
      func()
    }
  }
  // xhr.send(JSON.stringify({ 'username': 'BC0000294', 'password': '572589980' }))
  xhr.send(JSON.stringify({ 'username': 'CP0001184', 'password': '307844183' }))
}
