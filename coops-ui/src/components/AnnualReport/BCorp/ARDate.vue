<template>
  <v-card flat class="container">
    <div class="timeline">
      <label>Annual Report Date</label>
      <span class="date ar-date">{{this.toReadableDate(this.nextARDate)}}</span>
      <label>Filing Date</label>
      <span class="date file-date">Today ({{this.toReadableDate(new Date())}})</span>
    </div>
  </v-card>
</template>

<script lang="ts">
import { Component } from 'vue-property-decorator'
import { mapState } from 'vuex'
import DateMixin from '@/mixins/date-mixin'

@Component({
  computed: {
    ...mapState(['nextARDate'])
  }
})
export default class ARDate extends DateMixin {
  readonly nextARDate!: string
}
</script>

<style lang="scss" scoped>
@import '@/assets/styles/theme.scss';

.container {
  background: #ffffff;

  .timeline {
    display: flex;
    justify-content: space-between;

    label {
      font-weight: 700;
    }

    .date {
      margin-right: 4.5rem;
    }
  }
}
</style>
