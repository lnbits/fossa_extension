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
      recentpay: recentpay,
      tab: 'lnurl',
      ln: '',
      address: '',
      onchain_liquid: 'BTC/BTC',
      payment_options: ['lnurl', 'ln', 'onchain', 'liquid']
    }
  },
  methods: {
    async sendLNaddress() {
      try {
        const response = await LNbits.api.request(
          'GET',
          `/fossa/api/v1/ln/${lnurl}/${this.ln}`,
          ''
        )
        if (response.data) {
          this.ln = ''
          this.notifyUser('Payment should be with you shortly', 'positive')
          this.connectWebsocket(payment_id)
        }
        window.location.reload()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
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
          `/fossa/api/v1/boltz/${lnurl}/${this.onchain_liquid}/${this.address}`,
          ''
        )
        if (response.data) {
          this.ln = ''
          this.notifyUser('Payment should be with you shortly', 'positive')
        }
      } catch (error) {
        LNbits.utils.notifyApiError(error)
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
    notifyUser(message, type) {
      this.$q.notify({
        message,
        type,
        spinner: type === 'positive',
        timeout: 5000
      })
    }
  }
})
