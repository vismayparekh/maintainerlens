<script setup>
import { ref } from 'vue'

const props = defineProps({
  issue: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
})

const levels = {
  high: 'High',
  moderate: 'Moderate',
  low: 'Low',
  needs_review: 'Needs review',
}
const storageKey = `maintainerlens:issue-severity:${props.issue.url}`
const severityOverride = ref('')
const saveError = ref('')

try {
  const saved = props.readOnly ? null : localStorage.getItem(storageKey)
  if (Object.hasOwn(levels, saved)) severityOverride.value = saved
} catch {
  // The suggestion is still readable in browsers that disable storage.
}

function setSeverity(event) {
  const value = event.target.value
  try {
    if (value) localStorage.setItem(storageKey, value)
    else localStorage.removeItem(storageKey)
    severityOverride.value = value
    saveError.value = ''
  } catch {
    event.target.value = severityOverride.value
    saveError.value = 'This browser could not save your severity choice.'
  }
}
</script>

<template>
  <section class="similar-section">
    <div class="section-title">
      <h3>Severity</h3>
    </div>
    <p class="severity-reason">
      <strong>Suggested {{ levels[issue.severity.level] }}</strong>
      <span>{{ issue.severity.reason }}</span>
    </p>
    <label v-if="!readOnly" class="review-field severity-field">
      <span class="field-label">Severity decision</span>
      <select :value="severityOverride" @change="setSeverity">
        <option value="">Use suggestion</option>
        <option v-for="(label, level) in levels" :key="level" :value="level">{{ label }}</option>
      </select>
    </label>
    <p v-if="saveError" class="severity-note" role="alert">{{ saveError }}</p>
    <p v-else-if="severityOverride" class="severity-note" role="status">
      Your choice is saved in this browser.
    </p>
  </section>
</template>
