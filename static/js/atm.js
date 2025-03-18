window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  delimiters: ['${', '}'],
  data() {
    return {
      fossa_id: fossa_id,
      lnurl: lnurl,
      boltz: boltz,
      amount_sat: amount_sat,
      used: used,
      p: p,
      tab: 'lnurl',
      ln: '',
      address: '',
      onchain_liquid: 'BTC/BTC',
      recentpay: recentpay,
      payment_options: ['lnurl', 'ln', 'onchain', 'liquid']
    }
  },
  methods: {
    async sendLNaddress() {
      try {
        const response = await LNbits.api.request(
          'GET',
          `/fossa/api/v1/ln/${this.fossa_id}/${this.p}/${this.ln}`,
          ''
        )
        if (response.data) {
          this.ln = ''
          this.notifyUser('Payment should be with you shortly', 'positive')
          this.connectWebsocket(payment_id)
        }
        window.location.reload()
      } catch (error) {
        this.notifyApiError(error)
      }
    },
    sendOnchainAddress() {
      this.onchain_liquid = 'BTCtempBTC'
      this.sendAddress()
    },
    sendLiquidAddress() {
      this.onchain_liquid = 'L-BTCtempBTC'
      this.sendAddress()
    },
    async sendAddress() {
      try {
        const response = await LNbits.api.request(
          'GET',
          `/fossa/api/v1/boltz/${this.fossa_id}/${this.p}/${this.onchain_liquid}/${this.address}`,
          ''
        )
        if (response.data) {
          this.ln = ''
          this.notifyUser('Payment should be with you shortly', 'positive')
        }
      } catch (error) {
        this.notifyApiError(error)
      }
    },
    connectWebsocket(payment_id) {
      const protocol = location.protocol === 'https:' ? 'wss://' : 'ws://'
      const localUrl = `${protocol}${document.domain}:${location.port}/api/v1/ws/${review_id}` // Ensure review_id is defined or passed correctly
      this.connection = new WebSocket(localUrl)
      this.connection.onmessage = () => {
        this.notifyUser('Payment sent!', 'positive')
      }
    },
    closeParseDialog() {
      setTimeout(() => {
        clearInterval(this.parse.paymentChecker)
      }, 10000)
    },
    focusInput(el) {
      this.$nextTick(() => this.$refs[el].focus())
    },
    msatoshiFormat(value) {
      return LNbits.utils.formatSat(value / 1000)
    },
    showParseDialog() {
      this.parse.show = true
      this.parse.invoice = null
      this.parse.copy.show =
        window.isSecureContext && navigator.clipboard?.readText !== undefined
      this.parse.data.request = ''
      this.parse.data.comment = ''
      this.parse.data.paymentChecker = null
      this.focusInput('textArea')
    },
    notifyUser(message, type) {
      this.$q.notify({
        message,
        type,
        spinner: type === 'positive',
        timeout: 5000
      })
    },
    notifyApiError(error) {
      LNbits.utils.notifyApiError(error)
    }
  }
})
