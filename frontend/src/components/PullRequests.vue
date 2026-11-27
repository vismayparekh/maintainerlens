<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, ref } from 'vue'
import { isStaticDemo, loadDemoRepository } from '../demo'

const loading = defineModel('loading', { type: Boolean, default: false })
const props = defineProps({
  generationNotice: { type: String, default: '' },
  demoAccessKey: { type: String, default: '' },
})
const pulls = ref([])
const loadedRepository = ref('')
const selected = ref(null)
const details = ref(null)
const brief = ref(null)
const listError = ref('')
const detailError = ref('')
const briefError = ref('')
const loadingDetails = ref(false)
const loadingBrief = ref(false)
let detailsRequest = null
let briefRequest = null

const activePull = computed(() => details.value?.pull_request ?? selected.value)
const description = computed(() => {
  const body = activePull.value?.body
  if (!body) return ''
  return DOMPurify.sanitize(marked.parse(body, { async: false }), {
    FORBID_TAGS: ['img', 'iframe', 'video', 'audio', 'svg', 'math'],
  })
})

function statusLabel(status) {
  return status[0].toUpperCase() + status.slice(1)
}

async function requestJson(url, options) {
  const response = await fetch(url, options)
  if (response.ok) return response.json()
  const payload = await response.json().catch(() => null)
  throw new Error(typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status}).`)
}

function resetDetails() {
  detailsRequest?.abort()
  briefRequest?.abort()
  detailsRequest = null
  briefRequest = null
  loadingDetails.value = false
  loadingBrief.value = false
  details.value = null
  brief.value = null
  detailError.value = ''
  briefError.value = ''
}

function pullUrl(number, action = '') {
  const params = new URLSearchParams({ repository: loadedRepository.value })
  return `/api/pull-requests/${number}${action}?${params}`
}

async function loadPullRequests(repository, limit) {
  if (loading.value) return
  const repo = repository.trim()
  if (!repo) {
    listError.value = 'Enter a GitHub repository such as psf/requests.'
    return
  }
  loading.value = true
  listError.value = ''
  resetDetails()
  selected.value = null
  pulls.value = []
  loadedRepository.value = ''
  try {
    const params = new URLSearchParams({ repository: repo, limit: String(limit) })
    const result = isStaticDemo
      ? (await loadDemoRepository(repo)).pullRequests.map((details) => details.pull_request)
      : (await requestJson(`/api/pull-requests?${params}`)).pull_requests
    loadedRepository.value = repo
    pulls.value = result
    if (pulls.value.length) void selectPull(pulls.value[0])
  } catch (error) {
    listError.value = error.message
  } finally {
    loading.value = false
  }
}

async function selectPull(pull) {
  if (selected.value === pull && (details.value || loadingDetails.value)) return
  resetDetails()
  selected.value = pull
  const request = new AbortController()
  detailsRequest = request
  loadingDetails.value = true
  try {
    const result = isStaticDemo
      ? (await loadDemoRepository(loadedRepository.value)).pullRequests.find((example) => example.pull_request.number === pull.number)
      : await requestJson(pullUrl(pull.number), { signal: request.signal })
    if (detailsRequest !== request) return
    details.value = result
    if (isStaticDemo) brief.value = result.example_brief
  } catch (error) {
    if (detailsRequest === request) detailError.value = error.message
  } finally {
    if (detailsRequest === request) {
      detailsRequest = null
      loadingDetails.value = false
    }
  }
}

async function generateBrief() {
  if (!details.value || loadingBrief.value || props.generationNotice) return
  const request = new AbortController()
  briefRequest = request
  loadingBrief.value = true
  briefError.value = ''
  try {
    const result = await requestJson(pullUrl(activePull.value.number, '/analyze'), {
      method: 'POST',
      signal: request.signal,
      headers: props.demoAccessKey ? { 'X-MaintainerLens-Access-Key': props.demoAccessKey } : {},
    })
    if (briefRequest === request) brief.value = result
  } catch (error) {
    if (briefRequest === request) briefError.value = error.message
  } finally {
    if (briefRequest === request) {
      briefRequest = null
      loadingBrief.value = false
    }
  }
}

defineExpose({ loadPullRequests })
</script>

<template>
  <div class="pull-request-workspace">
    <p v-if="listError" class="notice notice-error" role="alert">{{ listError }}</p>
    <p v-else-if="loading" class="load-status" role="status">Loading public pull requests…</p>
    <section v-else-if="!pulls.length" class="panel issue-detail">
      {{ loadedRepository ? 'No open pull requests found for this repository.' : 'Fetch pull requests from a public GitHub repository.' }}
    </section>

    <section v-else class="triage-layout">
      <aside class="issue-panel panel" :aria-label="isStaticDemo ? 'Example pull requests' : 'Open pull requests'">
        <div class="panel-heading">
          <h2>{{ isStaticDemo ? 'Example pull requests' : 'Open pull requests' }} <span class="count-pill">{{ pulls.length }}</span></h2>
        </div>
        <div class="issue-list">
          <button
            v-for="pull in pulls"
            :key="pull.number"
            class="issue-row"
            :class="{ selected: selected?.number === pull.number }"
            :aria-pressed="selected?.number === pull.number"
            @click="selectPull(pull)"
          >
            <span class="issue-row-top">
              <span class="issue-number">#{{ pull.number }}</span>
              <span class="label-chip">{{ isStaticDemo ? 'Example' : statusLabel(pull.status) }}</span>
            </span>
            <span class="issue-row-title">{{ pull.title }}</span>
            <span v-if="pull.author" class="issue-row-meta">{{ pull.author }}</span>
          </button>
        </div>
      </aside>

      <div v-if="activePull" class="detail-column">
        <article class="panel issue-detail">
          <div class="detail-kicker">
            <a :href="activePull.url" target="_blank" rel="noreferrer">{{ loadedRepository }} › #{{ activePull.number }} ↗</a>
            <span class="label-chip">{{ isStaticDemo ? 'Example' : statusLabel(activePull.status) }}</span>
          </div>
          <h2 class="issue-title">{{ activePull.title }}</h2>
          <div v-if="details" class="detail-badges">
            <span class="label-chip">{{ details.head_branch }} → {{ details.base_branch }}</span>
            <span class="label-chip">{{ details.changed_files }} changed {{ details.changed_files === 1 ? 'file' : 'files' }}</span>
            <span class="label-chip">+{{ details.additions }} / −{{ details.deletions }}</span>
          </div>
          <section class="description-section">
            <div class="section-title"><h3>{{ isStaticDemo ? 'Pull request in brief' : 'Pull request description' }}</h3></div>
            <div v-if="description" class="issue-description" v-html="description"></div>
            <p v-else class="issue-description-empty">No description provided.</p>
          </section>
          <p v-if="loadingDetails" class="load-status" role="status">Loading changed files and issue references…</p>
          <div v-if="detailError" class="notice notice-error" role="alert">
            {{ detailError }} <button class="text-button" @click="selectPull(selected)">Retry</button>
          </div>
          <template v-if="details">
            <section class="similar-section">
              <div class="section-title">
                <h3>Changed files</h3>
                <span v-if="details.files.length < details.changed_files">
                  Showing {{ details.files.length }} of {{ details.changed_files }}
                </span>
              </div>
              <ul v-if="details.files.length" class="pull-file-list">
                <li v-for="file in details.files" :key="file.path">
                  <code>{{ file.path }}</code>
                  <span>{{ file.status }} · +{{ file.additions }} / −{{ file.deletions }}</span>
                </li>
              </ul>
              <p v-else class="empty-similar">No changed files reported.</p>
            </section>
            <section class="similar-section">
              <div class="section-title"><h3>Issue references in the description</h3></div>
              <ul v-if="details.issue_references.length" class="pull-references">
                <li v-for="reference in details.issue_references" :key="reference.url">
                  <a :href="reference.url" target="_blank" rel="noreferrer">{{ reference.repository }} #{{ reference.number }} ↗</a>
                </li>
              </ul>
              <p v-else class="empty-similar">No closing references or issue links found in the description.</p>
            </section>
          </template>
        </article>

        <article v-if="details" class="panel ai-panel">
          <h3>{{ isStaticDemo ? 'Saved AI review brief' : 'AI review brief' }}</h3>
          <p class="ai-empty">{{ isStaticDemo ? 'From the six-PR development benchmark.' : 'Uses the pull request description and file metadata. Open GitHub to review the diff.' }}</p>
          <p v-if="briefError" class="notice notice-error" role="alert">{{ briefError }}</p>
          <div v-if="brief" class="analysis-summary">
            <span class="field-label">Summary</span>
            <p>{{ brief.summary }}</p>
            <span class="field-label">Review checklist</span>
            <ul class="pull-review-checklist">
              <li v-for="(step, index) in brief.checklist" :key="index">{{ step }}</li>
            </ul>
          </div>
          <button v-if="!isStaticDemo && !generationNotice" class="button button-secondary analyze-button" :disabled="loadingBrief" @click="generateBrief">
            {{ loadingBrief ? 'Generating review brief…' : brief ? 'Regenerate review brief' : 'Generate review brief' }}
          </button>
          <p v-else-if="generationNotice" class="ai-empty">{{ generationNotice }}</p>
        </article>
      </div>
    </section>
  </div>
</template>
