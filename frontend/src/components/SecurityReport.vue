<script setup>
import { ref } from 'vue'

const props = defineProps({ guidance: { type: Object, required: true } })
const message = ref('')

async function copyReply() {
  try {
    await navigator.clipboard.writeText(props.guidance.reply)
    message.value = 'Private-reporting reply copied.'
  } catch {
    message.value = 'Select the reply text to copy it manually.'
  }
}
</script>

<template>
  <section class="similar-section">
    <div class="section-title"><h3>Possible security report</h3></div>
    <p class="severity-reason">{{ guidance.reason }}</p>
    <p class="security-help">
      Use <strong>Report a vulnerability</strong> on GitHub when it’s available, or follow the repository’s security policy for a private contact.
    </p>
    <div class="detail-badges">
      <a v-if="guidance.security_url" :href="guidance.security_url" class="button button-secondary" target="_blank" rel="noreferrer">Open GitHub security page ↗</a>
      <a v-if="guidance.policy_url" :href="guidance.policy_url" class="text-button" target="_blank" rel="noreferrer">Check security policy ↗</a>
    </div>
    <label class="review-field security-reply">
      <span class="field-label">Private-reporting reply</span>
      <textarea :value="guidance.reply" rows="4" readonly />
    </label>
    <button class="button button-secondary" @click="copyReply">Copy private-reporting reply</button>
    <p v-if="message" class="review-message" role="status">{{ message }}</p>
  </section>
</template>
