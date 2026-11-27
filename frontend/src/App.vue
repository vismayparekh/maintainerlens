<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onMounted, ref } from 'vue'
import Discussions from './components/Discussions.vue'
import IssueSeverity from './components/IssueSeverity.vue'
import PullRequests from './components/PullRequests.vue'
import SecurityReport from './components/SecurityReport.vue'
import { demoRepositories, isStaticDemo, loadDemoRepository } from './demo'

const categories = ['Bug', 'Question', 'Feature request', 'Other']
const filters = ['All', ...categories]
const linkParams = new URLSearchParams(window.location.search)
const linkedRepository = linkParams.get('repository')?.trim()
const linkedNumber = linkParams.get('issue')
const linkedIssue = !isStaticDemo && linkedRepository && /^[1-9]\d*$/.test(linkedNumber ?? '')
const repository = ref(linkedIssue ? linkedRepository : 'scikit-learn/scikit-learn')
const issueLimit = ref(10)
const inboxView = ref('issues')
const pullRequestsView = ref(null)
const discussionsView = ref(null)
const loadingPullRequests = ref(false)
const loadingDiscussions = ref(false)
const issues = ref([])
const loadedIssueRepository = ref('')
const selectedNumber = ref(null)
const categoryFilter = ref('All')
const searchQuery = ref('')
const loadingIssues = ref(false)
const relatedStatus = ref('idle')
const labelSuggestionsStatus = ref(null)
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
const replyTrial = ref(null)
const replyText = ref('')
const replyChecklist = ref('')
const replyLoading = ref(false)
const replySaving = ref(false)
const replyMessage = ref('')
const exportError = ref('')
const publicDemo = ref(false)
const demoGeneration = ref(false)
const demoAccessKey = ref('')
const generationNotice = computed(() => {
  if (!publicDemo.value) return ''
  if (!demoGeneration.value) return 'AI generation is currently unavailable in this live demo.'
  return demoAccessKey.value.trim() ? '' : 'Enter a demo access key above to generate a fresh result.'
})
let analysisRequest = null
let relatedRequest = null
let replyRequest = null

const isPullRequestsView = computed(() => inboxView.value === 'pull-requests')
const isDiscussionsView = computed(() => inboxView.value === 'discussions')
const loadingInbox = computed(() => ({
  issues: loadingIssues.value,
  'pull-requests': loadingPullRequests.value,
  discussions: loadingDiscussions.value,
})[inboxView.value])
const inboxCopy = {
  issues: {
    title: 'Make the next issue easier to triage.',
    description: 'Review incoming reports, surface related issues, and prepare a human-reviewed summary in one place.',
    limit: 'Open issues',
    items: 'issues',
  },
  'pull-requests': {
    title: 'Get oriented before reviewing a pull request.',
    description: 'See which files changed, find issue references, and prepare a review checklist.',
    limit: 'Open pull requests',
    items: 'pull requests',
  },
  discussions: {
    title: 'Catch up on repository discussions.',
    description: 'Browse recent threads, read accepted answers, and open the conversation on GitHub.',
    limit: 'Recent discussions',
    items: 'discussions',
  },
}
const activeInbox = computed(() => inboxCopy[inboxView.value])

function fetchInbox() {
  if (isPullRequestsView.value) {
    return pullRequestsView.value?.loadPullRequests(repository.value, issueLimit.value)
  }
  if (isDiscussionsView.value) {
    return discussionsView.value?.loadDiscussions(repository.value, issueLimit.value)
  }
  return fetchIssues()
}

function selectInbox(view) {
  if (view === inboxView.value) return
  inboxView.value = view
  if (isStaticDemo) void fetchInbox()
}

onMounted(async () => {
  if (isStaticDemo || linkedIssue) void fetchInbox()
  if (isStaticDemo) return
  try {
    const response = await fetch('/api/deployment')
    if (response.ok) {
      const settings = await response.json()
      publicDemo.value = settings.public_demo === true
      demoGeneration.value = settings.demo_generation === true
    }
  } catch {
    // The API enforces any hosting limits even if status cannot be loaded.
  }
})

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
  clearReplyReview()
  analysisRequest?.abort()
  analysisRequest = null
  loadingAnalysis.value = false
  analysis.value = null
  analysisError.value = ''
  reviewedSummary.value = ''
  reviewedCategory.value = ''
  reviewMessage.value = ''
}

function clearReplyReview() {
  replyRequest?.abort()
  replyRequest = null
  replyTrial.value = null
  replyText.value = ''
  replyChecklist.value = ''
  replyLoading.value = false
  replySaving.value = false
  replyMessage.value = ''
}

function selectIssue(issue) {
  if (selectedIssue.value === issue) return
  selectedNumber.value = issue.number
  clearReview()
}

function generationHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  if (publicDemo.value && demoAccessKey.value.trim()) {
    headers['X-MaintainerLens-Access-Key'] = demoAccessKey.value.trim()
  }
  return headers
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
  labelSuggestionsStatus.value = null
  issues.value = []
  selectedNumber.value = null
  clearReview()
  try {
    const repo = repository.value.trim()
    const result = isStaticDemo
      ? await loadDemoRepository(repo)
      : await fetchRepositoryIssues(repo)
    loadedIssueRepository.value = repo
    issues.value = result.issues
    labelSuggestionsStatus.value = result.label_suggestions_status ?? null
    selectedNumber.value = result.issues[0]?.number ?? null
    statusMessage.value = isStaticDemo
      ? `${result.issues.length} curated issue examples from ${repo}.`
      : linkedIssue
      ? `Loaded issue #${linkedNumber} from ${repo}.`
      : result.issues.length
      ? `Loaded ${result.issues.length} open issues and compared against ${result.historical_issue_count} recently closed issues.`
      : 'No open issues were found for this repository.'
    if (result.related_lookup_id) void fetchRelatedIssues(result.related_lookup_id)
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : 'Could not load issues.'
  } finally {
    loadingIssues.value = false
  }
}

async function fetchRepositoryIssues(repo) {
  if (linkedIssue) {
    const params = new URLSearchParams({ repository: repo })
    const response = await fetch(`/api/issues/${linkedNumber}?${params}`)
    if (!response.ok) throw new Error(await responseMessage(response))
    return { issues: [await response.json()] }
  }
  const params = new URLSearchParams({
    repository: repo,
    limit: String(issueLimit.value),
    include_label_suggestions: 'true',
  })
  const response = await fetch(`/api/issues?${params}`)
  if (!response.ok) throw new Error(await responseMessage(response))
  return response.json()
}

async function generateAnalysis() {
  const issue = selectedIssue.value
  if (!issue || issue.security_guidance || analysisRequest || generationNotice.value) return
  const request = new AbortController()
  analysisRequest = request
  loadingAnalysis.value = true
  analysisError.value = ''
  reviewMessage.value = ''
  try {
    const response = await fetch('/api/issues/analyze', {
      method: 'POST',
      headers: generationHeaders(),
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

async function startReplyTrial(mode) {
  const issue = selectedIssue.value
  if (!issue || issue.security_guidance || replySaving.value || (mode === 'assisted' && generationNotice.value)) return
  clearReplyReview()
  replyTrial.value = {
    id: crypto.randomUUID(),
    mode,
    startedAt: performance.now(),
    original: null,
    submission: null,
    saved: false,
  }
  if (mode === 'manual') return

  const request = new AbortController()
  replyRequest = request
  replyLoading.value = true
  try {
    const response = await fetch('/api/issues/draft-reply', {
      method: 'POST',
      headers: generationHeaders(),
      signal: request.signal,
      body: JSON.stringify({
        title: issue.title,
        body: issue.body,
        related_issues: issue.similar_issues.map((match) => ({
          issue_number: match.number,
          issue_title: match.title,
          issue_url: match.url,
        })),
      }),
    })
    if (!response.ok) throw new Error(await responseMessage(response))
    const draft = await response.json()
    if (replyRequest !== request) return
    replyText.value = draft.reply
    replyChecklist.value = draft.checklist.map((step) => `- [ ] ${step}`).join('\n')
    replyTrial.value.original = { reply: replyText.value, checklist: replyChecklist.value }
  } catch (error) {
    if (replyRequest !== request) return
    replyTrial.value = null
    replyMessage.value = error instanceof Error ? error.message : 'Could not draft the reply.'
  } finally {
    if (replyRequest === request) {
      replyRequest = null
      replyLoading.value = false
    }
  }
}

async function saveReplyReview() {
  const issue = selectedIssue.value
  const trial = replyTrial.value
  if (!issue || !trial || trial.saved || replyLoading.value || replySaving.value || !replyText.value.trim()) return
  trial.submission ??= {
    trial_id: trial.id,
    issue_number: issue.number,
    issue_title: issue.title,
    issue_url: issue.url,
    mode: trial.mode,
    duration_ms: Math.round(performance.now() - trial.startedAt),
    original_reply: trial.original?.reply ?? null,
    original_checklist: trial.original?.checklist ?? null,
    reviewed_reply: replyText.value,
    reviewed_checklist: replyChecklist.value,
  }

  replySaving.value = true
  replyMessage.value = ''
  try {
    const response = await fetch('/api/reply-reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(trial.submission),
    })
    if (!response.ok) throw new Error(await responseMessage(response))
    if (replyTrial.value !== trial) return
    trial.saved = true
    replyMessage.value = 'Reply review saved locally.'
  } catch (error) {
    if (replyTrial.value !== trial) return
    replyMessage.value = error instanceof Error ? error.message : 'Could not save the reply review.'
  } finally {
    if (replyTrial.value === trial) replySaving.value = false
  }
}

async function copyReply() {
  const trial = replyTrial.value
  try {
    await navigator.clipboard.writeText(replyText.value)
    if (replyTrial.value === trial) replyMessage.value = 'Reply copied.'
  } catch {
    if (replyTrial.value === trial) replyMessage.value = 'Could not copy. You can select the reply text manually.'
  }
}

async function downloadReviews(kind) {
  downloadingReviews.value = true
  exportError.value = ''
  const isReply = kind === 'reply'
  try {
    const response = await fetch(isReply ? '/api/reply-reviews/export' : '/api/reviews/export')
    if (!response.ok) throw new Error(await responseMessage(response))
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = isReply ? 'maintainer_reply_trials.csv' : 'maintainer_reviews.csv'
    link.click()
    URL.revokeObjectURL(objectUrl)
  } catch (error) {
    exportError.value =
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
        <span class="privacy-indicator"><span class="status-dot"></span> {{ isStaticDemo ? 'Portfolio demo' : publicDemo ? 'Live demo' : 'Local workspace' }}</span>
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
          <p class="eyebrow">GITHUB TRIAGE WORKSPACE</p>
          <h1 v-if="isStaticDemo">Explore a GitHub maintainer’s workflow.</h1>
          <h1 v-else>{{ activeInbox.title }}</h1>
          <p v-if="isStaticDemo" class="intro-copy">
            Browse real issues, pull requests, and discussions from scikit-learn and pandas, then see how MaintainerLens performed in evaluation.
          </p>
          <p v-else class="intro-copy">{{ activeInbox.description }}</p>
        </div>
        <div class="intro-note">
          <span class="note-icon">✳</span>
          <span v-if="isStaticDemo">Explore saved AI briefs and a reviewed reply.<br /><strong>Examples are bundled with the demo.</strong></span>
          <span v-else>AI suggestions stay yours to review.<br /><strong>Nothing is posted to GitHub.</strong></span>
        </div>
      </section>

      <label v-if="publicDemo && demoGeneration" class="review-field hosted-access">
        <span class="field-label">Demo access key</span>
        <input v-model="demoAccessKey" type="password" autocomplete="off" spellcheck="false" />
      </label>

      <div v-if="!linkedIssue" class="inbox-view-switch filter-row" role="group" aria-label="Inbox view">
        <button class="filter-chip" :class="{ active: inboxView === 'issues' }" :aria-pressed="inboxView === 'issues'" @click="selectInbox('issues')">Issues</button>
        <button class="filter-chip" :class="{ active: isPullRequestsView }" :aria-pressed="isPullRequestsView" @click="selectInbox('pull-requests')">Pull requests</button>
        <button class="filter-chip" :class="{ active: isDiscussionsView }" :aria-pressed="isDiscussionsView" @click="selectInbox('discussions')">Discussions</button>
        <a v-if="isStaticDemo" class="filter-chip demo-anchor" href="#benchmarks">Benchmarks</a>
      </div>

      <div v-if="isStaticDemo" class="repository-bar demo-repo-bar">
        <label class="limit-field">
          <span class="field-label">Example repository</span>
          <select v-model="repository" :disabled="loadingInbox" @change="fetchInbox">
            <option v-for="repo in demoRepositories" :key="repo" :value="repo">{{ repo }}</option>
          </select>
        </label>
      </div>
      <form v-else-if="!linkedIssue" class="repository-bar" @submit.prevent="fetchInbox">
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
              :disabled="loadingInbox"
            />
          </span>
        </label>
        <label class="limit-field">
          <span class="field-label">{{ activeInbox.limit }}</span>
          <select v-model.number="issueLimit" :disabled="loadingInbox">
            <option :value="10">10 {{ activeInbox.items }}</option>
            <option :value="20">20 {{ activeInbox.items }}</option>
          </select>
        </label>
        <button class="button button-primary fetch-button" :disabled="loadingInbox">
          <span v-if="loadingInbox" class="spinner"></span>
          <span>{{ loadingInbox ? 'Loading…' : 'Fetch ' + activeInbox.items }}</span>
          <span v-if="!loadingInbox" aria-hidden="true">→</span>
        </button>
      </form>

      <PullRequests
        v-show="isPullRequestsView"
        ref="pullRequestsView"
        v-model:loading="loadingPullRequests"
        :generation-notice="generationNotice"
        :demo-access-key="publicDemo ? demoAccessKey.trim() : ''"
      />
      <Discussions
        v-if="!linkedIssue"
        v-show="isDiscussionsView"
        ref="discussionsView"
        v-model:loading="loadingDiscussions"
      />

      <template v-if="inboxView === 'issues'">
      <div v-if="pageError" class="notice notice-error" role="alert">
        <span class="notice-icon">!</span>
        <span>{{ pageError }}</span>
      </div>
      <div v-else-if="statusMessage" class="load-status" role="status">
        <span class="status-dot"></span>{{ statusMessage }}
      </div>
      <p v-else-if="linkedIssue && loadingIssues" class="load-status" role="status">Loading issue…</p>

      <section v-if="issues.length && !isStaticDemo && !linkedIssue" class="metrics-row" aria-label="Issue summary">
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

      <section v-if="issues.length" :class="{ 'triage-layout': !linkedIssue }">
        <aside v-if="!linkedIssue" class="issue-panel panel">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">INBOX</p>
              <h2>{{ isStaticDemo ? 'Example issues' : 'Open issues' }} <span class="count-pill">{{ visibleIssues.length }}</span></h2>
            </div>
            <button v-if="!isStaticDemo" class="icon-button" title="Refresh issues" @click="fetchIssues">
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
                <span>{{ issue.labels.slice(0, 2).join(' · ') || (isStaticDemo ? 'GitHub issue' : 'Unlabeled') }}</span>
                <span v-if="issue.security_guidance" class="match-count">Security review</span>
                <span v-else-if="issue.similar_issues.length" class="match-count">
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
                {{ loadedIssueRepository }} <span>›</span> #{{ selectedIssue.number }} ↗
              </a>
              <span v-if="!linkedIssue" class="open-label"><span class="status-dot"></span> {{ isStaticDemo ? 'Example' : 'Open' }}</span>
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

            <SecurityReport
              v-if="selectedIssue.security_guidance"
              :key="selectedIssue.url"
              :guidance="selectedIssue.security_guidance"
            />

            <section class="description-section">
              <div class="section-title">
                <h3>{{ isStaticDemo ? 'Report in brief' : 'Issue description' }}</h3>
                <span v-if="!isStaticDemo">{{ selectedIssue.body.length.toLocaleString() }} characters</span>
              </div>
              <div
                v-if="issueDescriptionHtml"
                class="issue-description"
                v-html="issueDescriptionHtml"
              ></div>
              <p v-else class="issue-description-empty">No description provided.</p>
            </section>

            <IssueSeverity
              v-if="!linkedIssue && selectedIssue.severity && !selectedIssue.security_guidance"
              :key="selectedIssue.url"
              :issue="selectedIssue"
              :read-only="isStaticDemo"
            />

            <section v-if="(labelSuggestionsStatus || (isStaticDemo && selectedIssue.suggested_labels)) && !selectedIssue.security_guidance" class="similar-section">
              <div class="section-title">
                <h3>Suggested GitHub labels</h3>
              </div>
              <p v-if="labelSuggestionsStatus === 'unavailable'" class="empty-similar">
                Could not load GitHub labels. Fetch issues again to retry.
              </p>
              <ul v-else-if="selectedIssue.suggested_labels?.length" class="suggested-label-list">
                <li v-for="label in selectedIssue.suggested_labels" :key="label.name">
                  <span class="label-chip">{{ label.name }}</span>
                  <span>{{ label.reason }}</span>
                </li>
              </ul>
              <p v-else class="empty-similar">No additional labels suggested.</p>
            </section>

            <section v-if="!linkedIssue && !selectedIssue.security_guidance" class="similar-section">
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
                      {{ isStaticDemo ? 'Benchmark example' : match.is_closed ? 'Closed history' : 'Open issue' }} · {{ match.category }}
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
              <p v-else class="empty-similar">{{ isStaticDemo ? 'No related issues in this example.' : 'No related issues passed the similarity filters.' }}</p>
            </section>
          </article>

          <article v-if="isStaticDemo" class="panel ai-panel">
            <h3>Example triage note</h3>
            <div class="analysis-summary">
              <p>{{ selectedIssue.example_summary.summary }}</p>
              <p>{{ selectedIssue.example_summary.rationale }}</p>
            </div>
          </article>
          <article v-else-if="!linkedIssue && !selectedIssue.security_guidance" class="panel ai-panel">
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
              v-if="!generationNotice"
              class="button button-secondary analyze-button"
              :disabled="loadingAnalysis"
              @click="generateAnalysis"
            >
              <span v-if="loadingAnalysis" class="spinner"></span>
              {{ loadingAnalysis ? 'Analyzing issue' : analysis ? 'Regenerate suggestion' : 'Generate AI suggestion' }}
              <span v-if="!loadingAnalysis" aria-hidden="true">✳</span>
            </button>
            <p v-else class="ai-empty">{{ generationNotice }}</p>
          </article>

          <article v-if="!isStaticDemo && !publicDemo && analysis" class="panel review-panel">
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

          <article v-if="isStaticDemo && selectedIssue.example_reply" class="panel review-panel">
            <h3>Example maintainer reply</h3>
            <div class="analysis-summary">
              <p>{{ selectedIssue.example_reply.reviewed }}</p>
              <span class="field-label">Reproduction checklist</span>
              <ul class="pull-review-checklist">
                <li v-for="step in selectedIssue.example_reply.checklist" :key="step">{{ step }}</li>
              </ul>
            </div>
            <details class="demo-original-reply">
              <summary>View original AI draft</summary>
              <p>{{ selectedIssue.example_reply.original }}</p>
            </details>
          </article>
          <article v-if="!isStaticDemo && !selectedIssue.security_guidance" class="panel review-panel">
            <h3>Maintainer reply</h3>
            <div class="review-actions reply-mode-actions">
              <button
                v-if="!generationNotice"
                class="button button-secondary"
                :disabled="replyLoading || replySaving"
                @click="startReplyTrial('assisted')"
              >{{ replyLoading ? 'Drafting reply…' : 'Generate reply draft' }}</button>
              <button
                class="button button-secondary"
                :disabled="replySaving"
                @click="startReplyTrial('manual')"
              >Write from scratch</button>
            </div>
            <template v-if="replyTrial && !replyLoading">
              <label class="review-field">
                <span class="field-label">Reply</span>
                <textarea v-model="replyText" rows="6" maxlength="3000" :readonly="Boolean(replyTrial.submission)" />
              </label>
              <label class="review-field">
                <span class="field-label">Reproduction checklist</span>
                <textarea
                  v-model="replyChecklist"
                  rows="4"
                  maxlength="2000"
                  :readonly="Boolean(replyTrial.submission)"
                  placeholder="Leave blank if reproduction does not apply"
                />
              </label>
              <div class="review-actions">
                <button
                  v-if="!publicDemo"
                  class="button button-primary"
                  :disabled="replySaving || replyTrial.saved || !replyText.trim()"
                  @click="saveReplyReview"
                >{{ replySaving ? 'Saving reply…' : 'Save reply review' }}</button>
                <button class="button button-secondary" :disabled="!replyText.trim()" @click="copyReply">
                  Copy reply
                </button>
              </div>
            </template>
            <p v-if="replyMessage" class="review-message" role="status">{{ replyMessage }}</p>
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
      </template>

      <section v-if="isStaticDemo" id="benchmarks" class="demo-benchmarks" aria-labelledby="benchmarks-heading">
        <div class="section-title">
          <h2 id="benchmarks-heading">Benchmarks</h2>
          <a class="topbar-link" href="https://github.com/vismayparekh/maintainerlens#reproduce-the-development-baseline" target="_blank" rel="noreferrer">Evaluation details ↗</a>
        </div>
        <div class="metrics-row demo-benchmark-metrics">
          <article class="metric-card">
            <span class="metric-label">ISSUE CLASSIFICATION</span>
            <strong>95% macro F1</strong>
            <span class="metric-detail">Rule-based baseline on 27 development issues</span>
          </article>
          <article class="metric-card">
            <span class="metric-label">DUPLICATE RETRIEVAL</span>
            <strong>10 → 17 of 20 pairs</strong>
            <span class="metric-detail">Text overlap vs. hybrid on the same 40-issue holdout</span>
          </article>
          <article class="metric-card">
            <span class="metric-label">PR REVIEW CHECKLISTS</span>
            <strong>10 of 12 points</strong>
            <span class="metric-detail">Assistant-rated actionability on six development briefs</span>
          </article>
        </div>
      </section>

      <footer class="app-footer">
        <span>MAINTAINERLENS <i>·</i> {{ isStaticDemo ? 'PORTFOLIO DEMO' : 'AI-ASSISTED, HUMAN-REVIEWED' }}</span>
        <a v-if="isStaticDemo || publicDemo" class="topbar-link" href="https://github.com/vismayparekh/maintainerlens#run-the-docker-demo" target="_blank" rel="noreferrer">{{ isStaticDemo ? 'Run the full app ↗' : 'Run the app locally ↗' }}</a>
        <div v-else class="review-export-actions">
          <button class="text-button" :disabled="downloadingReviews" @click="downloadReviews('triage')">
            Export saved reviews ↓
          </button>
          <button class="text-button" :disabled="downloadingReviews" @click="downloadReviews('reply')">
            Export reply reviews ↓
          </button>
        </div>
      </footer>
      <p v-if="exportError" class="review-message" role="status">{{ exportError }}</p>
    </main>
  </div>
</template>
