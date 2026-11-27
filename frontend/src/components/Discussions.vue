<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, ref } from 'vue'
import { isStaticDemo, loadDemoRepository } from '../demo'

const loading = defineModel('loading', { type: Boolean, default: false })
const discussions = ref([])
const repository = ref('')
const enabled = ref(true)
const selected = ref(null)
const details = ref(null)
const listError = ref('')
const detailError = ref('')
const loadingDetails = ref(false)
let detailRequest = null

const active = computed(() => details.value ?? selected.value)
const recentComments = computed(() =>
  details.value?.recent_comments.filter((comment) => comment.url !== details.value.answer?.url) ?? [],
)

function markdown(body) {
  return DOMPurify.sanitize(marked.parse(body, { async: false }), {
    FORBID_TAGS: ['img', 'iframe', 'video', 'audio', 'svg', 'math'],
  })
}

async function read(url, signal) {
  const response = await fetch(url, { signal })
  const payload = await response.json().catch(() => null)
  if (response.ok && payload) return payload
  throw new Error(typeof payload?.detail === 'string' ? payload.detail : 'Could not load GitHub Discussions.')
}

function resetDetails() {
  detailRequest?.abort()
  detailRequest = null
  loadingDetails.value = false
  details.value = null
  detailError.value = ''
}

async function loadDiscussions(input, limit) {
  if (loading.value) return
  if (!input.trim()) {
    listError.value = 'Enter a GitHub repository such as scikit-learn/scikit-learn.'
    return
  }
  loading.value = true
  listError.value = ''
  repository.value = input.trim()
  discussions.value = []
  selected.value = null
  resetDetails()
  try {
    const params = new URLSearchParams({ repository: repository.value, limit: String(limit) })
    const result = isStaticDemo
      ? { discussions_enabled: true, discussions: (await loadDemoRepository(repository.value)).discussions }
      : await read(`/api/discussions?${params}`)
    enabled.value = result.discussions_enabled
    discussions.value = result.discussions
    if (discussions.value.length) void selectDiscussion(discussions.value[0])
  } catch (error) {
    listError.value = error.message
  } finally {
    loading.value = false
  }
}

async function selectDiscussion(discussion) {
  if (selected.value === discussion && (details.value || loadingDetails.value)) return
  resetDetails()
  selected.value = discussion
  if (isStaticDemo) {
    details.value = discussion
    return
  }
  const request = new AbortController()
  detailRequest = request
  loadingDetails.value = true
  try {
    const params = new URLSearchParams({ repository: repository.value })
    const result = await read(`/api/discussions/${discussion.number}?${params}`, request.signal)
    if (detailRequest === request) details.value = result
  } catch (error) {
    if (detailRequest === request) detailError.value = error.message
  } finally {
    if (detailRequest === request) {
      detailRequest = null
      loadingDetails.value = false
    }
  }
}

defineExpose({ loadDiscussions })
</script>

<template>
  <div>
    <p v-if="listError" class="notice notice-error" role="alert">{{ listError }}</p>
    <p v-else-if="loading" class="load-status" role="status">Loading public discussions…</p>
    <section v-else-if="!discussions.length" class="panel issue-detail">
      <p v-if="!repository">Fetch discussions from a public GitHub repository.</p>
      <p v-else-if="!enabled">GitHub Discussions are disabled for this repository.</p>
      <p v-else>{{ isStaticDemo ? 'No saved discussions for this repository.' : 'No discussions found for this repository.' }}</p>
    </section>

    <section v-else class="triage-layout">
      <aside class="issue-panel panel" :aria-label="isStaticDemo ? 'Saved discussions' : 'Recent discussions'">
        <div class="panel-heading">
          <h2>{{ isStaticDemo ? 'Saved discussions' : 'Recent discussions' }} <span class="count-pill">{{ discussions.length }}</span></h2>
        </div>
        <div class="issue-list">
          <button
            v-for="discussion in discussions"
            :key="discussion.number"
            class="issue-row"
            :class="{ selected: selected?.number === discussion.number }"
            :aria-pressed="selected?.number === discussion.number"
            @click="selectDiscussion(discussion)"
          >
            <span class="issue-row-top">
              <span class="issue-number">#{{ discussion.number }}</span>
              <span class="label-chip">{{ discussion.category }}</span>
            </span>
            <span class="issue-row-title">{{ discussion.title }}</span>
            <span class="issue-row-meta">
              {{ discussion.author || 'Unknown author' }} · {{ discussion.comment_count }} {{ discussion.comment_count === 1 ? 'comment' : 'comments' }}
              <span v-if="discussion.answered">· Answered</span>
            </span>
          </button>
        </div>
      </aside>

      <div v-if="active" class="detail-column">
        <article class="panel issue-detail">
          <div class="detail-kicker">
            <a :href="active.url" target="_blank" rel="noreferrer">Open discussion #{{ active.number }} on GitHub ↗</a>
          </div>
          <h2 class="issue-title">{{ active.title }}</h2>
          <div class="detail-badges">
            <span class="label-chip">{{ active.category }}</span>
            <span v-if="active.answerable" class="label-chip">{{ active.answered ? 'Answered' : 'Unanswered' }}</span>
            <span v-for="label in active.labels" :key="label" class="label-chip">{{ label }}</span>
          </div>
          <p v-if="loadingDetails" class="load-status" role="status">Loading the discussion…</p>
          <div v-if="detailError" class="notice notice-error" role="alert">
            {{ detailError }} <button class="text-button" @click="selectDiscussion(selected)">Retry</button>
          </div>
          <template v-if="details">
            <section class="description-section">
              <div class="section-title"><h3>Discussion post</h3></div>
              <div v-if="details.body" class="issue-description" v-html="markdown(details.body)"></div>
              <p v-else class="issue-description-empty">No description provided.</p>
            </section>
            <section v-if="details.answer" class="similar-section">
              <div class="section-title"><h3>Accepted answer</h3></div>
              <a :href="details.answer.url" target="_blank" rel="noreferrer">{{ details.answer.author || 'View answer' }} ↗</a>
              <div class="issue-description" v-html="markdown(details.answer.body)"></div>
            </section>
            <section v-if="recentComments.length" class="similar-section">
              <div class="section-title"><h3>Recent comments</h3></div>
              <div v-for="comment in recentComments" :key="comment.url" class="discussion-comment">
                <a :href="comment.url" target="_blank" rel="noreferrer">{{ comment.author || 'View comment' }} ↗</a>
                <div class="issue-description" v-html="markdown(comment.body)"></div>
              </div>
            </section>
          </template>
        </article>
      </div>
    </section>
  </div>
</template>
