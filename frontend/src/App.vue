<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, ref } from 'vue'

const categories = ['Bug', 'Question', 'Feature request', 'Other']
const filters = ['All', ...categories]
const repository = ref('scikit-learn/scikit-learn')
const issueLimit = ref(10)
const issues = ref([])
const selectedNumber = ref(null)
const categoryFilter = ref('All')
const searchQuery = ref('')
const loadingIssues = ref(false)
const relatedStatus = ref('idle')
const loadingAnalysis = ref(false)
const savingReview = ref(false)
const downloadingReviews = ref(false)
const pageError = ref('')
const analysisError = ref('')
const statusMessage = ref('')
const analysis = ref(null)
const reviewedSummary = ref('')
const reviewedCategory = ref('')
const reviewMessage = ref('')
let analysisRequest = null
let relatedRequest = null

const selectedIssue = computed(
  () => issues.value.find((issue) => issue.number === selectedNumber.value) ?? null,
)

const issueDescriptionHtml = computed(() => {
  const body = selectedIssue.value?.body
  if (!body) return ''
  return DOMPurify.sanitize(marked.parse(body, { async: false }), {
    FORBID_TAGS: ['img', 'iframe', 'video', 'audio', 'svg', 'math'],
  })
})

const visibleIssues = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return issues.value.filter((issue) => {
    const matchesCategory =
      categoryFilter.value === 'All' || issue.category === categoryFilter.value
    const matchesQuery =
      !query ||
      issue.title.toLocaleLowerCase().includes(query) ||
      String(issue.number).includes(query)
    return matchesCategory && matchesQuery
  })
})

const categoryCounts = computed(() =>
  categories.reduce(
    (counts, category) => ({
      ...counts,
      [category]: issues.value.filter((issue) => issue.category === category).length,
    }),
    {},
  ),
)

function categoryClass(category) {
  return `category-${category.toLocaleLowerCase().replaceAll(' ', '-')}`
}

function clearReview() {
  analysisRequest?.abort()
  analysisRequest = null
  loadingAnalysis.value = false
  analysis.value = null
  analysisError.value = ''
  reviewedSummary.value = ''
  reviewedCategory.value = ''
  reviewMessage.value = ''
}

function selectIssue(issue) {
  if (selectedIssue.value === issue) return
  selectedNumber.value = issue.number
  clearReview()
}

async function responseMessage(response) {
  try {
    const payload = await response.json()
    return payload.detail || payload.message || `Request failed (${response.status}).`
  } catch {
    return `Request failed (${response.status}).`
  }
}

async function fetchRelatedIssues(lookupId) {
  const request = new AbortController()
  relatedRequest = request
  relatedStatus.value = 'loading'
  try {
    const response = await fetch(`/api/issues/related/${encodeURIComponent(lookupId)}`, {
      signal: request.signal,
    })
    if (!response.ok) throw new Error('Related issue search failed.')
    const matches = await response.json()
    if (relatedRequest !== request) return
    for (const issue of issues.value) {
      if (!issue.similar_issues.length && matches[issue.number]) {
        issue.similar_issues = matches[issue.number]
      }
    }
    relatedStatus.value = 'complete'
  } catch {
    if (relatedRequest === request) relatedStatus.value = 'unavailable'
  } finally {
    if (relatedRequest === request) relatedRequest = null
  }
}

async function fetchIssues() {
  if (loadingIssues.value) return
  if (!repository.value.trim()) {
    pageError.value = 'Enter a GitHub repository such as psf/requests.'
    return
  }
  loadingIssues.value = true
  pageError.value = ''
  statusMessage.value = ''
  relatedRequest?.abort()
  relatedRequest = null
  relatedStatus.value = 'idle'
  issues.value = []
  selectedNumber.value = null
  clearReview()
  try {
    const params = new URLSearchParams({
      repository: repository.value.trim(),
      limit: String(issueLimit.value),
    })
    const response = await fetch(`/api/issues?${params}`)
    if (!response.ok) throw new Error(await responseMessage(response))
    const result = await response.json()
    issues.value = result.issues
    selectedNumber.value = result.issues[0]?.number ?? null
    statusMessage.value = result.issues.length
      ? `Loaded ${result.issues.length} open issues and compared against ${result.historical_issue_count} recently closed issues.`
      : 'No open issues were found for this repository.'
    if (result.related_lookup_id) void fetchRelatedIssues(result.related_lookup_id)
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : 'Could not load issues.'
  } finally {
    loadingIssues.value = false
  }
}

async function generateAnalysis() {
  const issue = selectedIssue.value
  if (!issue || analysisRequest) return
  const request = new AbortController()
  analysisRequest = request
  loadingAnalysis.value = true
  analysisError.value = ''
  reviewMessage.value = ''
  try {
    const response = await fetch('/api/issues/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: request.signal,
      body: JSON.stringify({
        title: issue.title,
        body: issue.body,
      }),
    })
    if (!response.ok) throw new Error(await responseMessage(response))
    const result = await response.json()
    if (analysisRequest !== request) return
    analysis.value = result
    reviewedSummary.value = result.summary
    reviewedCategory.value = result.category
  } catch (error) {
    if (analysisRequest !== request) return
    analysisError.value =
      error instanceof Error ? error.message : 'AI analysis could not be completed.'
  } finally {
    if (analysisRequest === request) {
      analysisRequest = null
      loadingAnalysis.value = false
    }
  }
}

async function saveReview() {
  if (!selectedIssue.value || !analysis.value) return
  savingReview.value = true
  reviewMessage.value = ''
  try {
    const response = await fetch('/api/reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        issue_number: selectedIssue.value.number,
        issue_title: selectedIssue.value.title,
        issue_url: selectedIssue.value.url,
        ai_summary: analysis.value.summary,
        ai_category: analysis.value.category,
        reviewed_summary: reviewedSummary.value,
        reviewed_category: reviewedCategory.value,
      }),
    })
    if (!response.ok) throw new Error(await responseMessage(response))
    const result = await response.json()
    reviewMessage.value = result.message
  } catch (error) {
    reviewMessage.value =
      error instanceof Error ? error.message : 'Could not save this review.'
  } finally {
    savingReview.value = false
  }
}

async function downloadReviews() {
  downloadingReviews.value = true
  reviewMessage.value = ''
  try {
    const response = await fetch('/api/reviews/export')
    if (!response.ok) throw new Error(await responseMessage(response))
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = 'maintainer_reviews.csv'
    link.click()
    URL.revokeObjectURL(objectUrl)
  } catch (error) {
    reviewMessage.value =
      error instanceof Error ? error.message : 'Could not export saved reviews.'
  } finally {
    downloadingReviews.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="#" aria-label="MaintainerLens home">
        <span class="brand-mark">M</span>
        <span class="brand-name">Maintainer<span>Lens</span></span>
      </a>
      <div class="topbar-right">
        <span class="privacy-indicator"><span class="status-dot"></span> Local workspace</span>
        <a
          class="topbar-link"
          href="https://github.com/vismayparekh/maintainerlens"
          target="_blank"
          rel="noreferrer"
        >GitHub ↗</a>
      </div>
    </header>

    <main class="workspace">
      <section class="intro">
        <div>
          <p class="eyebrow">ISSUE TRIAGE WORKSPACE</p>
          <h1>Make the next issue easier to triage.</h1>
          <p class="intro-copy">
            Review incoming reports, surface related issues, and prepare a human-reviewed
            summary in one place.
          </p>
        </div>
        <div class="intro-note">
          <span class="note-icon">✳</span>
          <span>AI suggestions stay yours to review.<br /><strong>Nothing is posted to GitHub.</strong></span>
        </div>
      </section>

      <form class="repository-bar" @submit.prevent="fetchIssues">
        <label class="repo-field">
          <span class="field-label">GitHub repository</span>
          <span class="repo-input-wrap">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v13a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5z" />
              <path d="M8 7h8M8 11h8M8 15h5" />
            </svg>
            <input
              v-model="repository"
              autocomplete="url"
              placeholder="owner/repo"
              :disabled="loadingIssues"
            />
          </span>
        </label>
        <label class="limit-field">
          <span class="field-label">Open issues</span>
          <select v-model.number="issueLimit" :disabled="loadingIssues">
            <option :value="10">10 issues</option>
            <option :value="20">20 issues</option>
          </select>
        </label>
        <button class="button button-primary fetch-button" :disabled="loadingIssues">
          <span v-if="loadingIssues" class="spinner"></span>
          <span>{{ loadingIssues ? 'Loading issues' : 'Fetch issues' }}</span>
          <span v-if="!loadingIssues" aria-hidden="true">→</span>
        </button>
      </form>

      <div v-if="pageError" class="notice notice-error" role="alert">
        <span class="notice-icon">!</span>
        <span>{{ pageError }}</span>
      </div>
      <div v-else-if="statusMessage" class="load-status" role="status">
        <span class="status-dot"></span>{{ statusMessage }}
      </div>

      <section v-if="issues.length" class="metrics-row" aria-label="Issue summary">
        <div class="metric-card">
          <span class="metric-label">OPEN ISSUES</span>
          <strong>{{ issues.length }}</strong>
          <span class="metric-detail">in current review</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">BUG REPORTS</span>
          <strong>{{ categoryCounts.Bug }}</strong>
          <span class="metric-detail">rule-based suggestion</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">FEATURE REQUESTS</span>
          <strong>{{ categoryCounts['Feature request'] }}</strong>
          <span class="metric-detail">rule-based suggestion</span>
        </div>
        <div class="metric-card metric-repository">
          <span class="metric-label">REPOSITORY</span>
          <strong>{{ repository }}</strong>
          <span class="metric-detail">public GitHub issues</span>
        </div>
      </section>

      <section v-if="issues.length" class="triage-layout">
        <aside class="issue-panel panel">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">INBOX</p>
              <h2>Open issues <span class="count-pill">{{ visibleIssues.length }}</span></h2>
            </div>
            <button class="icon-button" title="Refresh issues" @click="fetchIssues">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M20 7v5h-5M4 17v-5h5" />
                <path d="M6.2 9a7 7 0 0 1 11.6-2L20 12M4 12l2.2 5a7 7 0 0 0 11.6-2" />
              </svg>
            </button>
          </div>

          <label class="search-box">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="10.8" cy="10.8" r="6.8" />
              <path d="m16 16 4 4" />
            </svg>
            <input v-model="searchQuery" placeholder="Search issues..." />
          </label>

          <div class="filter-row" aria-label="Filter by category">
            <button
              v-for="filter in filters"
              :key="filter"
              class="filter-chip"
              :class="{ active: categoryFilter === filter }"
              @click="categoryFilter = filter"
            >{{ filter }}</button>
          </div>

          <div class="issue-list">
            <button
              v-for="issue in visibleIssues"
              :key="issue.number"
              class="issue-row"
              :class="{ selected: selectedNumber === issue.number }"
              @click="selectIssue(issue)"
            >
              <span class="issue-row-top">
                <span class="issue-number">#{{ issue.number }}</span>
                <span class="category-badge" :class="categoryClass(issue.category)">
                  {{ issue.category }}
                </span>
              </span>
              <span class="issue-row-title">{{ issue.title }}</span>
              <span class="issue-row-meta">
                <span>{{ issue.labels.slice(0, 2).join(' · ') || 'Unlabeled' }}</span>
                <span v-if="issue.similar_issues.length" class="match-count">
                  {{ issue.similar_issues.length }} related
                </span>
              </span>
            </button>
            <p v-if="!visibleIssues.length" class="empty-filter">
              No issues match these filters.
            </p>
          </div>

          <footer class="issue-panel-footer">
            <span class="status-dot"></span>
            Similarity scores are signals, not confidence
          </footer>
        </aside>

        <section v-if="selectedIssue" class="detail-column">
          <article class="panel issue-detail">
            <div class="detail-kicker">
              <a :href="selectedIssue.url" target="_blank" rel="noreferrer">
                {{ repository }} <span>›</span> #{{ selectedIssue.number }} ↗
              </a>
              <span class="open-label"><span class="status-dot"></span> Open</span>
            </div>
            <h2 class="issue-title">{{ selectedIssue.title }}</h2>
            <div class="detail-badges">
              <span class="category-badge" :class="categoryClass(selectedIssue.category)">
                {{ selectedIssue.category }}
              </span>
              <span v-for="label in selectedIssue.labels" :key="label" class="label-chip">
                {{ label }}
              </span>
            </div>

            <section class="description-section">
              <div class="section-title">
                <h3>Issue description</h3>
                <span>{{ selectedIssue.body.length.toLocaleString() }} characters</span>
              </div>
              <div
                v-if="issueDescriptionHtml"
                class="issue-description"
                v-html="issueDescriptionHtml"
              ></div>
              <p v-else class="issue-description-empty">No description provided.</p>
            </section>

            <section class="similar-section">
              <div class="section-title">
                <div>
                  <p class="eyebrow">CONTEXT</p>
                  <h3>Related issues</h3>
                </div>
                <span class="muted-caption">Review possible matches</span>
              </div>
              <div v-if="selectedIssue.similar_issues.length" class="similar-list">
                <a
                  v-for="match in selectedIssue.similar_issues"
                  :key="match.number"
                  class="similar-row"
                  :href="match.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  <span class="similar-icon">↗</span>
                  <span class="similar-copy">
                    <strong>#{{ match.number }} {{ match.title }}</strong>
                    <span>
                      {{ match.is_closed ? 'Closed history' : 'Open issue' }} · {{ match.category }}
                      · {{ match.method === 'semantic' ? 'Semantic similarity' : 'Text similarity' }}
                    </span>
                  </span>
                  <span class="similar-score">{{ Math.round(match.score * 100) }}%</span>
                </a>
              </div>
              <p v-else-if="relatedStatus === 'loading'" class="empty-similar" role="status">
                Searching for related issues…
              </p>
              <p v-else-if="relatedStatus === 'unavailable'" class="empty-similar" role="status">
                Semantic search is unavailable. Fetch issues again to retry.
              </p>
              <p v-else class="empty-similar">No related issues passed the similarity filters.</p>
            </section>
          </article>

          <article class="panel ai-panel">
            <div class="ai-panel-heading">
              <div class="ai-icon">✳</div>
              <div>
                <p class="eyebrow">AI ASSISTED</p>
                <h3>Summary &amp; triage suggestion</h3>
              </div>
              <span class="review-only">Review before using</span>
            </div>

            <p v-if="!analysis && !analysisError" class="ai-empty">
              Generate a concise summary and category suggestion for this issue.
              The issue text is sent to Hugging Face only when you request it.
            </p>
            <div v-if="analysisError" class="notice notice-error" role="alert">
              <span class="notice-icon">!</span><span>{{ analysisError }}</span>
            </div>
            <template v-if="analysis">
              <div class="analysis-summary">
                <span class="field-label">SUMMARY</span>
                <p>{{ analysis.summary }}</p>
                <p v-if="analysis.summary_truncated" class="summary-truncated-note" role="status">
                  This summary was shortened to fit the 500-character review limit.
                </p>
              </div>
              <div class="analysis-meta">
                <div>
                  <span class="field-label">SUGGESTED CATEGORY</span>
                  <span class="category-badge" :class="categoryClass(analysis.category)">
                    {{ analysis.category }}
                  </span>
                </div>
                <div class="rationale">
                  <span class="field-label">RATIONALE</span>
                  <p>{{ analysis.rationale }}</p>
                </div>
              </div>
            </template>
            <button
              class="button button-secondary analyze-button"
              :disabled="loadingAnalysis"
              @click="generateAnalysis"
            >
              <span v-if="loadingAnalysis" class="spinner"></span>
              {{ loadingAnalysis ? 'Analyzing issue' : analysis ? 'Regenerate suggestion' : 'Generate AI suggestion' }}
              <span v-if="!loadingAnalysis" aria-hidden="true">✳</span>
            </button>
          </article>

          <article v-if="analysis" class="panel review-panel">
            <div class="review-heading">
              <div>
                <p class="eyebrow">YOUR DECISION</p>
                <h3>Review and save</h3>
              </div>
              <span class="local-tag"><span class="status-dot"></span> Saved locally</span>
            </div>
            <label class="review-field">
              <span class="field-label">Reviewed summary</span>
              <textarea v-model="reviewedSummary" rows="4" maxlength="500"></textarea>
              <span class="character-count">{{ reviewedSummary.length }}/500</span>
            </label>
            <label class="review-field">
              <span class="field-label">Reviewed category</span>
              <select v-model="reviewedCategory">
                <option v-for="category in categories" :key="category" :value="category">
                  {{ category }}
                </option>
              </select>
            </label>
            <div class="review-actions">
              <p v-if="reviewMessage" class="review-message" role="status">
                {{ reviewMessage }}
              </p>
              <button
                class="button button-primary"
                :disabled="savingReview || !reviewedSummary.trim()"
                @click="saveReview"
              >
                {{ savingReview ? 'Saving review' : 'Save reviewed issue' }}
              </button>
            </div>
            <p class="privacy-footnote">
              The issue body is not saved. Your feedback stays on this machine and is never
              posted to GitHub.
            </p>
          </article>
        </section>

        <section v-else class="panel empty-detail">
          <div class="empty-art">⌁</div>
          <h2>Select an issue to begin</h2>
          <p>Choose an issue from the inbox to review its description and related reports.</p>
        </section>
      </section>

      <section v-else-if="!loadingIssues && !pageError" class="welcome-panel">
        <div class="welcome-icon">M</div>
        <p class="eyebrow">YOUR MAINTAINER WORKSPACE</p>
        <h2>Bring your issue queue into focus.</h2>
        <p>
          Enter a public GitHub repository above. MaintainerLens will organize open issues,
          surface similar reports, and help you prepare human-reviewed triage notes.
        </p>
        <div class="welcome-steps">
          <span><b>01</b> Load issues</span>
          <span><b>02</b> Explore context</span>
          <span><b>03</b> Review suggestions</span>
        </div>
      </section>

      <footer class="app-footer">
        <span>MAINTAINERLENS <i>·</i> AI-ASSISTED, HUMAN-REVIEWED</span>
        <button class="text-button" :disabled="downloadingReviews" @click="downloadReviews">
          {{ downloadingReviews ? 'Preparing export…' : 'Export saved reviews ↓' }}
        </button>
      </footer>
    </main>
  </div>
</template>
