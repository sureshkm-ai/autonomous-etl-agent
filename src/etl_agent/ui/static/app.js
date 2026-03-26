/**
 * Autonomous ETL Agent — Frontend Application
 * Handles story submission, SSE log streaming, run history, and pipeline detail view.
 */

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE = '/api/v1';

const STAGES = [
  { key: 'PENDING',           label: 'Pending',    icon: '⏳' },
  { key: 'PARSING',           label: 'Parsing',    icon: '📖' },
  { key: 'CODING',            label: 'Coding',     icon: '💻' },
  { key: 'TESTING',           label: 'Testing',    icon: '🧪' },
  { key: 'AWAITING_APPROVAL', label: 'Approval',   icon: '🛑' },
  { key: 'PR_CREATING',       label: 'PR',         icon: '🔀' },
  { key: 'DEPLOYING',         label: 'Deploying',  icon: '🚀' },
  { key: 'DONE',              label: 'Done',       icon: '✅' },
];

const STATUS_CLASSES = {
  DONE:              'bg-green-900 text-green-300 border-green-700',
  FAILED:            'bg-red-900 text-red-300 border-red-700',
  PENDING:           'bg-gray-800 text-gray-400 border-gray-700',
  PARSING:           'bg-indigo-900 text-indigo-300 border-indigo-700',
  CODING:            'bg-blue-900 text-blue-300 border-blue-700',
  TESTING:           'bg-purple-900 text-purple-300 border-purple-700',
  AWAITING_APPROVAL: 'bg-yellow-900 text-yellow-300 border-yellow-700',
  PR_CREATING:       'bg-teal-900 text-teal-300 border-teal-700',
  DEPLOYING:         'bg-orange-900 text-orange-300 border-orange-700',
};

// ─── Example Stories ─────────────────────────────────────────────────────────

const EXAMPLES = {
  rfm: `id: rfm_analysis
title: RFM Customer Segmentation
description: >
  Compute Recency, Frequency, and Monetary scores for Amazon customers
  based on their order history. Segment customers into Champions,
  Loyal, Potential, At Risk, and Lost cohorts using quintile bucketing.
source:
  path: s3://etl-raw/amazon_orders/
  format: parquet
target:
  path: s3://etl-processed/rfm_scores/
  format: delta
  partition_by: [rfm_segment]
transformations:
  - name: aggregate_orders
    operation: aggregate
    description: Compute recency, frequency, monetary per customer
    params:
      group_by: [customer_id]
      aggregations:
        - function: max
          column: order_date
          alias: last_order_date
        - function: count
          column: order_id
          alias: frequency
        - function: sum
          column: total_amount
          alias: monetary
  - name: compute_rfm_scores
    operation: enrich
    description: Add R/F/M scores using ntile(5) window functions
acceptance_criteria:
  - All customers present in the source are scored
  - No null values in rfm_segment column
  - Minimum coverage 80%
tags: [rfm, segmentation, analytics]`,

  geo: `id: geo_revenue
title: Geographic Revenue Analytics
description: >
  Join customers with orders and aggregate revenue by country and region.
  Flag high-value regions based on a revenue threshold.
source:
  path: s3://etl-raw/amazon_orders/
  format: parquet
target:
  path: s3://etl-processed/geo_revenue/
  format: delta
  partition_by: [country]
transformations:
  - name: join_customers
    operation: join
    description: Broadcast join orders with customer profile
    params:
      right_path: s3://etl-raw/amazon_customers/
      right_format: parquet
      join_keys: [customer_id]
      join_type: inner
  - name: aggregate_by_region
    operation: aggregate
    description: Sum revenue per country / region
    params:
      group_by: [country, region]
      aggregations:
        - function: sum
          column: total_amount
          alias: total_revenue
        - function: countDistinct
          column: customer_id
          alias: unique_customers
acceptance_criteria:
  - Row count matches distinct country/region combinations
  - No null country values in output
tags: [geo, revenue, analytics]`,

  campaign: `id: campaign_performance
title: iPhone 17 Campaign Optimizer
description: >
  Analyse marketing campaign performance for iPhone 17 product lines.
  Compute conversion rate, revenue per impression, and ROI percentage.
  Grade each campaign A through D.
source:
  path: s3://etl-raw/amazon_campaigns/
  format: parquet
target:
  path: s3://etl-processed/campaign_kpis/
  format: delta
transformations:
  - name: filter_iphone17
    operation: filter
    description: Keep only iPhone 17 related campaigns
    params:
      condition: "product_family LIKE '%iPhone 17%'"
  - name: compute_kpis
    operation: enrich
    description: Compute conversion_rate, revenue_per_impression, roi_pct, campaign_grade
acceptance_criteria:
  - All KPI columns present and non-null
  - campaign_grade is one of A, B, C, D
tags: [campaign, iphone17, kpi, analytics]`,

  join: `id: join_aggregate
title: Order Line Enrichment and Aggregation
description: >
  Join order lines with product catalogue, fill null prices,
  deduplicate, then aggregate monthly revenue by product category.
source:
  path: s3://etl-raw/order_lines/
  format: parquet
target:
  path: s3://etl-processed/monthly_category_revenue/
  format: delta
  partition_by: [year, month]
transformations:
  - name: join_products
    operation: join
    params:
      right_path: s3://etl-raw/products/
      right_format: parquet
      join_keys: [product_id]
      join_type: left
  - name: fill_null_price
    operation: fill_null
    params:
      fill_values:
        unit_price: 0.0
  - name: deduplicate
    operation: dedupe
    params:
      subset_cols: [order_id, product_id]
  - name: aggregate_monthly
    operation: aggregate
    params:
      group_by: [year, month, category]
      aggregations:
        - function: sum
          column: line_total
          alias: monthly_revenue
        - function: count
          column: order_id
          alias: order_count
acceptance_criteria:
  - No duplicate order_id/product_id pairs
  - monthly_revenue is non-negative
tags: [join, aggregate, revenue]`,
};

// ─── Utilities ────────────────────────────────────────────────────────────────

function getApiKey() {
  // Read from localStorage (user can set it in the UI) or fall back to empty
  return localStorage.getItem('etl_api_key') || '';
}

function apiFetch(path, options = {}) {
  const apiKey = getApiKey();
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'X-API-Key': apiKey } : {}),
      ...(options.headers || {}),
    },
  });
}

function formatDatetime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

function formatDuration(startIso, endIso) {
  if (!startIso) return '—';
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function buildStageBar(currentStatus) {
  return STAGES.map((stage) => {
    const stageIndex = STAGES.findIndex((s) => s.key === stage.key);
    const currentIndex = STAGES.findIndex((s) => s.key === currentStatus);
    const isFailed = currentStatus === 'FAILED';

    let cls = 'stage-step';
    if (isFailed && stageIndex === currentIndex) cls += ' stage-failed';
    else if (stageIndex < currentIndex) cls += ' stage-done';
    else if (stageIndex === currentIndex) cls += ' stage-active';
    else cls += ' stage-pending';

    return `<div class="${cls}" title="${stage.key}">
      <span>${stage.icon}</span>
      <span class="hidden sm:inline text-[10px] mt-0.5">${stage.label}</span>
    </div>`;
  }).join('<div class="stage-connector"></div>');
}

function statusBadge(status) {
  const cls = STATUS_CLASSES[status] || STATUS_CLASSES.PENDING;
  return `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cls}">${status}</span>`;
}

// ─── Index Page (Story Submission) ───────────────────────────────────────────

function initIndexPage() {
  const form = document.getElementById('storyForm');
  if (!form) return;

  // Example loaders
  document.querySelectorAll('.example-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const example = EXAMPLES[btn.dataset.example];
      if (example) document.getElementById('storyInput').value = example;
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const storyYaml = document.getElementById('storyInput').value.trim();
    if (!storyYaml) return;

    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ Submitting…';

    try {
      const res = await apiFetch('/stories', {
        method: 'POST',
        body: JSON.stringify({
          story_yaml: storyYaml,
          deploy: document.getElementById('deployCheck').checked,
          require_approval: document.getElementById('approvalCheck').checked,
          dry_run: document.getElementById('dryRunCheck').checked,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Submission failed');
      }

      const { run_id } = await res.json();
      showStatusCard(run_id);
    } catch (err) {
      alert(`Error: ${err.message}`);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = '🚀 Run Agent Pipeline';
    }
  });
}

function showStatusCard(runId) {
  const card = document.getElementById('statusCard');
  card.classList.remove('hidden');

  document.getElementById('runIdBadge').textContent = `Run: ${runId}`;
  document.getElementById('detailsLink').href = `/runs/${runId}`;

  const logOutput = document.getElementById('logOutput');
  const stageProgress = document.getElementById('stageProgress');

  stageProgress.innerHTML = buildStageBar('PENDING');
  logOutput.textContent = '';

  startSSEStream(runId, (msg) => {
    logOutput.textContent += msg + '\n';
    logOutput.parentElement.scrollTop = logOutput.parentElement.scrollHeight;
  }, (runData) => {
    stageProgress.innerHTML = buildStageBar(runData.status);
    updateRunLinks(runData);
  });
}

function updateRunLinks(runData) {
  const linksDiv = document.getElementById('runLinks');
  linksDiv.classList.remove('hidden');
  linksDiv.classList.add('flex');

  const setLink = (id, url) => {
    const el = document.getElementById(id);
    if (url) { el.href = url; el.classList.remove('hidden'); }
  };

  setLink('issueLink', runData.github_issue_url);
  setLink('prLink', runData.github_pr_url);
  setLink('artifactLink', runData.s3_artifact_url);
  if (runData.airflow_dag_run_id) {
    const el = document.getElementById('airflowLink');
    el.href = '#';
    el.classList.remove('hidden');
  }
}

// ─── SSE Log Streaming ────────────────────────────────────────────────────────

function startSSEStream(runId, onMessage, onUpdate) {
  const apiKey = getApiKey();
  const url = `${API_BASE}/runs/${runId}/logs${apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : ''}`;
  const es = new EventSource(url);

  es.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.log) onMessage(data.log);
      if (data.status) onUpdate(data);
      if (data.status === 'DONE' || data.status === 'FAILED') {
        es.close();
      }
    } catch (_) {
      onMessage(ev.data);
    }
  };

  es.onerror = () => {
    onMessage('[SSE connection closed]');
    es.close();
  };

  return es;
}

// ─── Run History Page ─────────────────────────────────────────────────────────

let _runsPage = 1;
const _runsPageSize = 20;

function initRunsPage() {
  const tbody = document.getElementById('runsTableBody');
  if (!tbody) return;

  loadRuns();

  document.getElementById('refreshBtn')?.addEventListener('click', loadRuns);
  document.getElementById('statusFilter')?.addEventListener('change', () => {
    _runsPage = 1;
    loadRuns();
  });
  document.getElementById('prevPage')?.addEventListener('click', () => {
    if (_runsPage > 1) { _runsPage--; loadRuns(); }
  });
  document.getElementById('nextPage')?.addEventListener('click', () => {
    _runsPage++;
    loadRuns();
  });
}

async function loadRuns() {
  const tbody = document.getElementById('runsTableBody');
  const statusFilter = document.getElementById('statusFilter')?.value || '';

  tbody.innerHTML = `<tr><td colspan="7" class="text-center py-12 text-gray-600">Loading…</td></tr>`;

  try {
    const params = new URLSearchParams({
      skip: (_runsPage - 1) * _runsPageSize,
      limit: _runsPageSize,
      ...(statusFilter ? { status: statusFilter } : {}),
    });

    const res = await apiFetch(`/runs?${params}`);
    if (!res.ok) throw new Error(res.statusText);
    const runs = await res.json();

    updateStats(runs);
    renderRunsTable(runs, tbody);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-12 text-red-500">Error: ${err.message}</td></tr>`;
  }
}

function updateStats(runs) {
  document.getElementById('statTotal').textContent = runs.length;
  document.getElementById('statDone').textContent = runs.filter((r) => r.status === 'DONE').length;
  document.getElementById('statFailed').textContent = runs.filter((r) => r.status === 'FAILED').length;
  const active = ['PARSING', 'CODING', 'TESTING', 'PR_CREATING', 'DEPLOYING', 'AWAITING_APPROVAL'];
  document.getElementById('statRunning').textContent = runs.filter((r) => active.includes(r.status)).length;
}

function renderRunsTable(runs, tbody) {
  if (!runs.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-12 text-gray-600">No runs found.</td></tr>`;
    return;
  }

  tbody.innerHTML = runs.map((run, idx) => `
    <tr class="hover:bg-gray-900 transition-colors">
      <td class="px-4 py-3 text-gray-600">${idx + 1 + (_runsPage - 1) * _runsPageSize}</td>
      <td class="px-4 py-3">
        <div class="font-medium text-gray-200 truncate max-w-xs">${run.pipeline_name || run.story_id || '—'}</div>
        <div class="text-xs text-gray-600 font-mono">${run.run_id?.slice(0, 8)}…</div>
      </td>
      <td class="px-4 py-3">${statusBadge(run.status)}</td>
      <td class="px-4 py-3 hidden sm:table-cell text-sm">
        ${run.tests_passed != null
          ? `<span class="text-green-400">${run.tests_passed}✓</span> <span class="text-red-400">${run.tests_failed || 0}✗</span>`
          : '<span class="text-gray-600">—</span>'}
      </td>
      <td class="px-4 py-3 hidden md:table-cell text-xs space-x-2">
        ${run.github_pr_url ? `<a href="${run.github_pr_url}" target="_blank" class="text-green-400 hover:underline">PR</a>` : ''}
        ${run.s3_artifact_url ? `<a href="${run.s3_artifact_url}" target="_blank" class="text-yellow-400 hover:underline">S3</a>` : ''}
        ${!run.github_pr_url && !run.s3_artifact_url ? '<span class="text-gray-600">—</span>' : ''}
      </td>
      <td class="px-4 py-3 hidden lg:table-cell text-xs text-gray-500">${formatDatetime(run.created_at)}</td>
      <td class="px-4 py-3">
        <a href="/runs/${run.run_id}" class="text-indigo-400 hover:underline text-xs">Details →</a>
      </td>
    </tr>
  `).join('');
}

// ─── Pipeline Detail Page ─────────────────────────────────────────────────────

function initPipelinePage() {
  const runId = window.__RUN_ID__;
  if (!runId) return;

  document.getElementById('runIdDisplay').textContent = `Run ID: ${runId}`;

  loadRunDetails(runId);

  // Start SSE if run is still active
  const logContent = document.getElementById('logContent');
  const sseStatus = document.getElementById('sseStatus');
  const autoScrollCheck = document.getElementById('autoScrollCheck');
  const logContainer = document.getElementById('logContainer');

  document.getElementById('clearLogsBtn')?.addEventListener('click', () => {
    logContent.textContent = '';
  });

  const es = startSSEStream(
    runId,
    (msg) => {
      logContent.textContent += msg + '\n';
      if (autoScrollCheck?.checked) {
        logContainer.scrollTop = logContainer.scrollHeight;
      }
    },
    (data) => {
      applyRunData(data);
    },
  );

  sseStatus.textContent = '● live';
  sseStatus.classList.add('text-green-500');
}

async function loadRunDetails(runId) {
  try {
    const res = await apiFetch(`/runs/${runId}`);
    if (!res.ok) throw new Error(res.statusText);
    const run = await res.json();
    applyRunData(run);
  } catch (err) {
    document.getElementById('pipelineTitle').textContent = `Error: ${err.message}`;
  }
}

function applyRunData(run) {
  // Title & status
  document.getElementById('pipelineTitle').textContent = run.pipeline_name || run.story_id || `Run ${run.run_id?.slice(0, 8)}`;
  const badge = document.getElementById('statusBadgeLarge');
  badge.className = `text-sm font-semibold px-3 py-1 rounded-full border mt-1 ${STATUS_CLASSES[run.status] || STATUS_CLASSES.PENDING}`;
  badge.textContent = run.status;

  // Stage bar
  document.getElementById('stageBar').innerHTML = buildStageBar(run.status);

  // Timing
  document.getElementById('detailStarted').textContent = formatDatetime(run.created_at);
  document.getElementById('detailDuration').textContent = formatDuration(run.created_at, run.updated_at);
  document.getElementById('detailRetries').textContent = run.retry_count ?? '0';

  // Tests
  document.getElementById('detailTestsPassed').textContent = run.tests_passed ?? '—';
  document.getElementById('detailTestsFailed').textContent = run.tests_failed ?? '—';
  document.getElementById('detailCoverage').textContent = run.coverage_pct != null ? `${run.coverage_pct}%` : '—';

  // Artifacts
  let hasArtifact = false;
  const setArtifactLink = (id, url) => {
    const el = document.getElementById(id);
    if (url) { el.href = url; el.classList.remove('hidden'); hasArtifact = true; }
  };
  setArtifactLink('linkIssue', run.github_issue_url);
  setArtifactLink('linkPR', run.github_pr_url);
  setArtifactLink('linkArtifact', run.s3_artifact_url);
  if (run.airflow_dag_run_id) {
    document.getElementById('linkAirflow').classList.remove('hidden');
    hasArtifact = true;
  }
  if (hasArtifact) document.getElementById('noArtifacts').classList.add('hidden');

  // Error
  if (run.error_message) {
    document.getElementById('errorCard').classList.remove('hidden');
    document.getElementById('errorMessage').textContent = run.error_message;
  }

  // Approval panel
  if (run.awaiting_approval) {
    document.getElementById('approvalPanel').classList.remove('hidden');
    document.getElementById('approveBtn').onclick = () => approveRun(run.run_id);
    document.getElementById('rejectBtn').onclick = () => rejectRun(run.run_id);
  }
}

async function approveRun(runId) {
  await apiFetch(`/runs/${runId}/approve`, { method: 'POST' });
  document.getElementById('approvalPanel').classList.add('hidden');
}

async function rejectRun(runId) {
  await apiFetch(`/runs/${runId}/reject`, { method: 'POST' });
  document.getElementById('approvalPanel').classList.add('hidden');
}

// ─── Inline CSS (injected as <style> via JS for portability) ─────────────────

function injectStyles() {
  const style = document.createElement('style');
  style.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap');
    body { font-family: 'JetBrains Mono', 'Courier New', monospace; }

    .example-btn {
      font-size: 11px;
      padding: 3px 10px;
      border-radius: 9999px;
      border: 1px solid #374151;
      color: #9ca3af;
      background: transparent;
      cursor: pointer;
      transition: all 0.15s;
    }
    .example-btn:hover { border-color: #6366f1; color: #a5b4fc; }

    .stage-step {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 4px 8px;
      border-radius: 6px;
      border: 1px solid transparent;
      font-size: 11px;
      min-width: 44px;
      transition: all 0.2s;
    }
    .stage-connector {
      flex: 1;
      height: 1px;
      background: #374151;
      min-width: 8px;
    }
    .stage-done    { background: #064e3b; border-color: #059669; color: #6ee7b7; }
    .stage-active  { background: #1e1b4b; border-color: #6366f1; color: #a5b4fc; animation: pulse 1.5s infinite; }
    .stage-pending { background: #111827; border-color: #374151; color: #4b5563; }
    .stage-failed  { background: #450a0a; border-color: #ef4444; color: #fca5a5; }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.6; }
    }

    /* Tailwind-like base utilities (minimal set for browsers without Tailwind CDN) */
    .hidden { display: none !important; }
    .flex   { display: flex; }
    .inline-block { display: inline-block; }
  `;
  document.head.appendChild(style);
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  injectStyles();
  initIndexPage();
  initRunsPage();
  initPipelinePage();
});
