<template>
  <v-dialog v-model="dialog" width="60rem" id="delete-error-dialog">
      <v-card>
        <v-card-title id="error-dialogue-title" v-if="errors.length > 0 || warnings.length < 1">
          Unable to Delete Filing
        </v-card-title>
        <v-card-title id="warning-dialogue-title" v-else>
          Filing Deleted with Warnings
        </v-card-title>
        <v-card-text id="dialogue-text">
          <p class="genErr" v-if="errors.length + warnings.length < 1">
            We were unable to delete your filing.
          </p>
          <p class="genErr" v-else-if="errors.length > 0">
            We were unable to delete your filing due to the following errors:
          </p>
          <p class="genErr" v-else>
            Please note the following:
          </p>
          <p class="genErr" v-for="(error, index) in errors" :key="index">
            {{error.error}}
          </p>
          <p class="genErr" v-for="(warning, index) in warnings" :key="index">
            {{warning.warning}}
          </p>

          <ErrorContact />

        </v-card-text>
        <v-divider class="my-0"></v-divider>
        <v-card-actions>
          <v-btn id="okay-btn" color="primary" text @click="okay()">Okay</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
</template>

<script lang="ts">
import { Component, Vue, Prop, Emit } from 'vue-property-decorator'
import ErrorContact from '@/components/ErrorContact.vue'

@Component({
  components: { ErrorContact }
})
export default class DeleteErrorDialog extends Vue {
  // Prop to display the dialog.
  @Prop() private dialog: boolean

  // Prop containing error messages.
  @Prop() private errors: object[]

  // Prop containing warning messages.
  @Prop() private warnings: object[]

  // Pass click event to parent.
  @Emit() private okay () { }
}
</script>

<style lang="scss" scoped>
@import '@/assets/styles/theme.scss';

.genErr {
  font-size: 0.9rem;
}
</style>
