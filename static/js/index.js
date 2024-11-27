window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  data() {
    return {
      tab: 'mails',
      protocol: window.location.protocol,
      location: window.location.hostname,
      filter: '',
      currency: 'USD',
      deviceString: '',
      lnurlValue: '',
      fossa: [],
      atmLinks: [],
      boltzToggleState: false,
      fossaTable: {
        columns: [
          {
            name: 'title',
            align: 'left',
            label: 'title',
            field: 'title'
          },
          {
            name: 'currency',
            align: 'left',
            label: 'currency',
            field: 'currency'
          },
          {
            name: 'wallet',
            align: 'left',
            label: 'wallet',
            field: 'wallet'
          },
          {
            name: 'key',
            align: 'left',
            label: 'key',
            field: 'key'
          }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      atmTable: {
        columns: [
          {
            name: 'id',
            align: 'left',
            label: 'ID',
            field: 'id'
          },
          {
            name: 'deviceid',
            align: 'left',
            label: 'Device ID',
            field: 'deviceid'
          },
          {
            name: 'sats',
            align: 'left',
            label: 'Sats',
            field: 'sats'
          },
          {
            name: 'time',
            align: 'left',
            label: 'Date',
            field: 'time'
          }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      settingsDialog: {
        show: false,
        data: {}
      },
      formDialog: {
        show: false,
        data: {}
      }
    }
  },
  methods: {
    cancelFormDialog() {
      this.formDialog.show = false
      this.clearFormDialog()
    },
    closeFormDialog() {
      this.clearFormDialog()
      this.formDialog.data = {
        is_unique: false
      }
    },
    sendFormData() {
      if (!this.formDialog.data.profit) {
        this.formDialog.data.profit = 0
      }
      if (this.formDialog.data.id) {
        this.updateFossa(this.g.user.wallets[0].adminkey, this.formDialog.data)
      } else {
        this.createFossa(this.g.user.wallets[0].adminkey, this.formDialog.data)
      }
    },
    createFossa(wallet, data) {
      const updatedData = {}
      for (const property in data) {
        if (data[property]) {
          updatedData[property] = data[property]
        }
      }
      LNbits.api
        .request('POST', '/fossa/api/v1', wallet, updatedData)
        .then(response => {
          this.fossa.push(response.data)
          this.formDialog.show = false
          this.clearFormDialog()
        })
        .catch(LNbits.utils.notifyApiError)
    },
    getFossa() {
      LNbits.api
        .request('GET', '/fossa/api/v1', this.g.user.wallets[0].adminkey)
        .then(response => {
          if (response.data) {
            this.fossa = response.data
          }
        })
        .catch(LNbits.utils.notifyApiError)
    },
    getAtmPayments() {
      LNbits.api
        .request('GET', '/fossa/api/v1/atm', this.g.user.wallets[0].adminkey)
        .then(function (response) {
          if (response.data) {
            this.atmLinks = response.data.map(mapatmpayments)
          }
        })
        .catch(LNbits.utils.notifyApiError)
    },
    deleteFossa(fossaId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this pay link?')
        .onOk(() => {
          LNbits.api
            .request(
              'DELETE',
              '/fossa/api/v1/' + fossaId,
              this.g.user.wallets[0].adminkey
            )
            .then(() => {
              this.fossa = _.reject(this.fossa, obj => {
                return obj.id === fossaId
              })
            })
            .catch(LNbits.utils.notifyApiError)
        })
    },
    deleteATMLink(atmId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this atm link?')
        .onOk(function () {
          LNbits.api
            .request(
              'DELETE',
              '/fossa/api/v1/atm/' + atmId,
              this.g.user.wallets[0].adminkey
            )
            .then(function (response) {
              this.atmLinks = _.reject(this.atmLinks, function (obj) {
                return obj.id === atmId
              })
            })
            .catch(LNbits.utils.notifyApiError)
        })
    },
    openUpdateFossa(fossaId) {
      const fossa = _.findWhere(this.fossa, {
        id: fossaId
      })
      this.formDialog.data = _.clone(fossa)
      if (fossa.boltz) {
        this.boltzToggleState = true
      } else {
        this.boltzToggleState = false
      }
      this.formDialog.show = true
    },
    openFossaSettings(fossaId) {
      const fossa = _.findWhere(this.fossa, {
        id: fossaId
      })
      this.deviceString = `${this.protocol}//${this.location}/fossa/api/v1/lnurl/${fossa.id},${fossa.key},${fossa.currency}`
      this.settingsDialog.data = _.clone(fossa)
      this.settingsDialog.show = true
    },
    handleBoltzToggleChange(val) {
      if (val) {
        this.formDialog.data.boltz = true
      } else {
        this.formDialog.data.boltz = false
      }
    },
    updateFossa(wallet, data) {
      const updatedData = {}
      for (const property in data) {
        if (data[property]) {
          updatedData[property] = data[property]
        }
      }

      LNbits.api
        .request('PUT', '/fossa/api/v1/' + updatedData.id, wallet, updatedData)
        .then(response => {
          this.fossa = _.reject(this.fossa, obj => {
            return obj.id === updatedData.id
          })
          this.fossa.push(response.data)
          this.formDialog.show = false
          this.clearFormDialog()
        })
        .catch(LNbits.utils.notifyApiError)
    },
    clearFormDialog() {
      this.formDialog.data = {
        lnurl_toggle: false,
        show_message: false,
        show_ack: false,
        show_price: 'None',
        title: ''
      }
    },
    exportFossaCSV() {
      LNbits.utils.exportCSV(this.fossaTable.columns, this.fossa)
    },
    exportAtmCSV() {
      LNbits.utils.exportCSV(this.atmTable.columns, this.atmLinks)
    },
    openATMLink(deviceid, p) {
      const url =
        this.location + '/fossa/api/v1/lnurl/' + deviceid + '?atm=1&p=' + p
      data = {
        url: url
      }
      LNbits.api
        .request(
          'POST',
          '/fossa/api/v1/lnurlencode',
          this.g.user.wallets[0].adminkey,
          data
        )
        .then(response => {
          window.open('/fossa/atm?lightning=' + response.data)
        })
        .catch(LNbits.utils.notifyApiError)
    }
  },
  created() {
    this.getFossa()
    // this.getatmpayments()
    LNbits.api
      .request('GET', '/api/v1/currencies')
      .then(response => {
        this.currency = ['USD', ...response.data]
      })
      .catch(LNbits.utils.notifyApiError)
  }
})
