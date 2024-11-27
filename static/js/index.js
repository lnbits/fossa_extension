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
            name: 'theId',
            align: 'left',
            label: 'id',
            field: 'id'
          },
          {
            name: 'key',
            align: 'left',
            label: 'key',
            field: 'key'
          },
          {
            name: 'wallet',
            align: 'left',
            label: 'wallet',
            field: 'wallet'
          },
          {
            name: 'device',
            align: 'left',
            label: 'device',
            field: 'device'
          },
          {
            name: 'currency',
            align: 'left',
            label: 'currency',
            field: 'currency'
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
    cancellnurldevice() {
      this.formDialoglnurldevice.show = false
      this.clearFormDialoglnurldevice()
    },
    closeFormDialog() {
      this.clearFormDialoglnurldevice()
      this.formDialog.data = {
        is_unique: false
      }
    },
    sendFormDatalnurldevice() {
      if (!this.formDialoglnurldevice.data.profit) {
        this.formDialoglnurldevice.data.profit = 0
      }
      if (this.formDialoglnurldevice.data.id) {
        this.updatelnurldevice(
          this.g.user.wallets[0].adminkey,
          this.formDialoglnurldevice.data
        )
      } else {
        this.createlnurldevice(
          this.g.user.wallets[0].adminkey,
          this.formDialoglnurldevice.data
        )
      }
    },

    createlnurldevice(wallet, data) {
      var updatedData = {}
      for (const property in data) {
        if (data[property]) {
          updatedData[property] = data[property]
        }
      }
      LNbits.api
        .request('POST', '/fossa/api/v1', wallet, updatedData)
        .then(response => {
          this.fossa.push(response.data)
          this.formDialoglnurldevice.show = false
          this.clearFormDialoglnurldevice()
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
    getatmpayments: function () {
      LNbits.api
        .request(
          'GET',
          '/lnurldevice/api/v1/atm',
          this.g.user.wallets[0].adminkey
        )
        .then(function (response) {
          if (response.data) {
            this.atmLinks = response.data.map(mapatmpayments)
          }
        })
        .catch(function (error) {
          LNbits.utils.notifyApiError(error)
        })
    },
    deleteFossa: function (fossaId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this pay link?')
        .onOk(() => {
          LNbits.api
            .request(
              'DELETE',
              '/lnurldevice/api/v1/lnurlpos/' + fossaId,
              this.g.user.wallets[0].adminkey
            )
            .then(response => {
              this.fossa = _.reject(this.fossa, obj => {
                return obj.id === fossaId
              })
            })
            .catch(LNbits.utils.notifyApiError)
        })
    },
    deleteATMLink: function (atmId) {
      LNbits.utils
        .confirmDialog('Are you sure you want to delete this atm link?')
        .onOk(function () {
          LNbits.api
            .request(
              'DELETE',
              '/lnurldevice/api/v1/atm/' + atmId,
              this.g.user.wallets[0].adminkey
            )
            .then(function (response) {
              this.atmLinks = _.reject(this.atmLinks, function (obj) {
                return obj.id === atmId
              })
            })
            .catch(function (error) {
              LNbits.utils.notifyApiError(error)
            })
        })
    },
    openUpdatelnurldeviceLink: function (lnurldeviceId) {
      var lnurldevice = _.findWhere(this.lnurldeviceLinks, {
        id: lnurldeviceId
      })
      this.formDialoglnurldevice.data = _.clone(lnurldevice._data)
      if (lnurldevice.device == 'atm' && lnurldevice.extra == 'boltz') {
        this.boltzToggleState = true
      } else {
        this.boltzToggleState = false
      }
      this.formDialoglnurldevice.show = true
    },
    openlnurldeviceSettings: function (lnurldeviceId) {
      var lnurldevice = _.findWhere(this.lnurldeviceLinks, {
        id: lnurldeviceId
      })
      this.settingsDialog.data = _.clone(lnurldevice._data)
      this.settingsDialog.show = true
    },
    handleBoltzToggleChange(val) {
      if (val) {
        this.formDialoglnurldevice.data.extra = 'boltz'
      } else {
        this.formDialoglnurldevice.data.extra = ''
      }
    },
    updateFossa: function (wallet, data) {
      var updatedData = {}
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
          this.formDialoglnurldevice.show = false
          this.clearFormDialog()
        })
        .catch(function (error) {
          LNbits.utils.notifyApiError(error)
        })
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
    exportlnurldeviceCSV: function () {
      LNbits.utils.exportCSV(
        this.lnurldevicesTable.columns,
        this.lnurldeviceLinks
      )
    },
    exportATMCSV: function () {
      LNbits.utils.exportCSV(this.atmTable.columns, this.atmLinks)
    },
    openATMLink: function (deviceid, p) {
      var url =
        this.location +
        '/lnurldevice/api/v1/lnurl/' +
        deviceid +
        '?atm=1&p=' +
        p
      data = {
        url: url
      }
      LNbits.api
        .request(
          'POST',
          '/lnurldevice/api/v1/lnurlencode',
          this.g.user.wallets[0].adminkey,
          data
        )
        .then(function (response) {
          window.open('/lnurldevice/atm?lightning=' + response.data)
        })
        .catch(function (error) {
          LNbits.utils.notifyApiError(error)
        })
    }
  },
  created() {
    this.getFossa()
    // this.getatmpayments()
    LNbits.api
      .request('GET', '/api/v1/currencies')
      .then(response => {
        this.currency = ['sat', 'USD', ...response.data]
      })
      .catch(LNbits.utils.notifyApiError)
  }
})
