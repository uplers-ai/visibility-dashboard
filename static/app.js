// ======================================================================
// LLM Visibility Dashboard — frontend
// ======================================================================

const API = {
  locations: () => fetch('/api/locations').then(r => r.json()),
  llms: () => fetch('/api/llms').then(r => r.json()),
  createAudit: (body) => fetch('/api/audits', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  }).then(async r => { if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); }),
  listAudits: () => fetch('/api/audits').then(r => r.json()),
  getAudit: (id) => fetch(`/api/audits/${id}`).then(r => r.json()),
  getResults: (id) => fetch(`/api/audits/${id}/results`).then(r => r.json()),
  deleteAudit: (id) => fetch(`/api/audits/${id}`, { method: 'DELETE' }),
  listSets: () => fetch('/api/query-sets').then(r => r.json()),
  saveSet: (body) => fetch('/api/query-sets', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  }).then(async r => { if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); }),
};

const fmt = {
  pct: (n) => `${Number(n).toFixed(1)}%`,
  shortDate: (iso) => {
    if (!iso) return '—';
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleString();
  },
  location: (a) => [a.location_city, a.location_state, a.location_country].filter(Boolean).join(', ') || '—',
  escape: (s) => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])),
};

function showNotice(msg, kind='info') {
  const el = document.getElementById('notice');
  if (!el) return alert(msg);
  el.textContent = msg;
  el.className = `notice ${kind}`;
  el.style.display = 'block';
  if (kind !== 'error') setTimeout(() => { el.style.display = 'none'; }, 5000);
}

// ======================================================================
// Index page (new audit form)
// ======================================================================

async function initIndexPage() {
  const [locations, llmInfo, querySets] = await Promise.all([
    API.locations(), API.llms(), API.listSets()
  ]);

  // Country / state / city cascading dropdowns
  const countrySel = document.getElementById('country');
  const stateSel = document.getElementById('state');
  const citySel = document.getElementById('city');

  const countries = Object.keys(locations).sort((a, b) => {
    if (a === 'United States') return -1;
    if (b === 'United States') return 1;
    return a.localeCompare(b);
  });

  countrySel.innerHTML = countries.map(c => `<option value="${fmt.escape(c)}">${fmt.escape(c)}</option>`).join('');
  countrySel.value = 'United States';

  function refreshStates() {
    const states = Object.keys(locations[countrySel.value] || {}).sort();
    stateSel.innerHTML = states.map(s => `<option value="${fmt.escape(s)}">${fmt.escape(s)}</option>`).join('');
    if (countrySel.value === 'United States' && states.includes('California')) stateSel.value = 'California';
    refreshCities();
  }

  function refreshCities() {
    const cities = (locations[countrySel.value] || {})[stateSel.value] || [];
    citySel.innerHTML = cities.map(c => `<option value="${fmt.escape(c)}">${fmt.escape(c)}</option>`).join('');
  }

  countrySel.addEventListener('change', refreshStates);
  stateSel.addEventListener('change', refreshCities);
  refreshStates();

  // LLM checkboxes
  const llmGrid = document.getElementById('llm-grid');
  llmGrid.innerHTML = llmInfo.all.map(name => {
    const isAvailable = llmInfo.available.includes(name);
    return `
      <label class="checkbox-pill" title="${isAvailable ? '' : 'API key not configured'}">
        <input type="checkbox" name="llm" value="${name}" ${isAvailable ? 'checked' : 'disabled'} />
        <span class="pill-label">${name}</span>
      </label>
    `;
  }).join('');
  const missing = llmInfo.all.filter(n => !llmInfo.available.includes(n));
  document.getElementById('llm-availability').textContent =
    missing.length ? `Disabled (no API key): ${missing.join(', ')}` : 'All LLMs configured.';

  // Query sets dropdown
  const qSetSel = document.getElementById('query_set');
  qSetSel.innerHTML = '<option value="">— None —</option>' +
    querySets.map(s => `<option value="${s.id}">${fmt.escape(s.name)} (${s.queries.length})</option>`).join('');

  qSetSel.addEventListener('change', () => {
    const set = querySets.find(s => String(s.id) === qSetSel.value);
    if (!set) return;
    const lines = set.queries.map(q => q.intent ? `[${q.intent}] ${q.text}` : q.text);
    document.getElementById('queries').value = lines.join('\n');
    updateEstimate();
  });

  // Live estimate
  const queriesInput = document.getElementById('queries');
  const runsInput = document.getElementById('runs_per_prompt');
  const estimate = document.getElementById('estimate');

  function updateEstimate() {
    const queries = parseQueries(queriesInput.value);
    const llms = [...document.querySelectorAll('input[name="llm"]:checked')].length;
    const runs = parseInt(runsInput.value, 10) || 1;
    const total = queries.length * llms * runs;
    const minutes = Math.ceil(total * 2.5 / 60);
    estimate.textContent = total
      ? `~${total} LLM calls (~${minutes} min)`
      : 'Add queries to estimate';
  }
  queriesInput.addEventListener('input', updateEstimate);
  runsInput.addEventListener('change', updateEstimate);
  llmGrid.addEventListener('change', updateEstimate);
  updateEstimate();

  // Save set button
  document.getElementById('save-set-btn').addEventListener('click', async () => {
    const setName = document.getElementById('set_name').value.trim();
    const queries = parseQueries(queriesInput.value);
    if (!setName) return showNotice('Enter a name to save the set', 'error');
    if (!queries.length) return showNotice('Add at least one query first', 'error');
    try {
      await API.saveSet({ name: setName, queries });
      showNotice(`Saved query set "${setName}"`, 'success');
    } catch (e) {
      showNotice(`Failed to save: ${e.message}`, 'error');
    }
  });

  // Submit
  document.getElementById('audit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const queries = parseQueries(queriesInput.value);
    const llms = [...document.querySelectorAll('input[name="llm"]:checked')].map(i => i.value);
    if (!queries.length) return showNotice('Add at least one query', 'error');
    if (!llms.length) return showNotice('Select at least one LLM', 'error');

    const body = {
      name: document.getElementById('name').value.trim(),
      target_company: document.getElementById('target_company').value.trim(),
      country: countrySel.value || null,
      state: stateSel.value || null,
      city: citySel.value || null,
      llms,
      runs_per_prompt: parseInt(runsInput.value, 10),
      queries,
    };

    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = 'Starting…';
    try {
      const { id } = await API.createAudit(body);
      window.location.href = `/results/${id}`;
    } catch (err) {
      showNotice(`Failed to start audit: ${err.message}`, 'error');
      btn.disabled = false;
      btn.textContent = 'Run Audit';
    }
  });
}

function parseQueries(text) {
  return text.split('\n')
    .map(l => l.trim())
    .filter(Boolean)
    .map(line => {
      const m = line.match(/^\[([^\]]+)\]\s*(.+)$/);
      return m ? { text: m[2].trim(), intent: m[1].trim() } : { text: line, intent: 'General' };
    });
}

// ======================================================================
// Results page
// ======================================================================

async function initResultsPage() {
  const auditId = window.location.pathname.split('/').pop();
  let pollTimer = null;

  async function refresh() {
    let data;
    try {
      data = await API.getResults(auditId);
    } catch (e) {
      console.error(e);
      return;
    }
    renderStatus(data.audit);
    if (data.audit.status === 'completed') {
      renderResults(data.audit, data.results);
      clearInterval(pollTimer);
    } else if (data.audit.status === 'failed') {
      clearInterval(pollTimer);
    }
  }

  await refresh();
  pollTimer = setInterval(refresh, 3000);
}

function renderStatus(audit) {
  document.getElementById('audit-name').textContent = audit.name;
  document.getElementById('audit-meta').textContent =
    `${fmt.location(audit)} · ${audit.llms.join(', ')} · ${audit.runs_per_prompt} run(s) per query · target: ${audit.target_company}`;

  const badge = document.getElementById('status-badge');
  badge.className = `badge badge-${audit.status}`;
  badge.textContent = audit.status;

  document.getElementById('status-detail').textContent = audit.error_message || '';

  const total = audit.total_queries || 1;
  const done = audit.completed_queries || 0;
  const pct = Math.min(100, Math.round((done / total) * 100));
  document.getElementById('progress-fill').style.width = `${pct}%`;
  document.getElementById('progress-percent').textContent = `${pct}%`;
  document.getElementById('progress-message').textContent = audit.progress_message || '—';
  document.getElementById('completed-text').textContent = `${done} / ${total}`;
}

function renderResults(audit, results) {
  document.getElementById('results-content').style.display = 'block';
  const a = audit.analysis || {};

  // score cards
  const overall = a.overall || {};
  const sg = document.getElementById('score-grid');
  const rankClass = overall.target_rank <= 3 ? 'accent' : overall.target_rank <= 10 ? 'warning' : 'danger';
  sg.innerHTML = `
    <div class="score-card primary">
      <div class="label">Visibility Score</div>
      <div class="value accent">${fmt.pct(overall.visibility_score || 0)}</div>
      <div class="detail">${overall.target_mentions || 0} mentions in ${overall.total_queries || 0} queries</div>
    </div>
    <div class="score-card">
      <div class="label">Ranking</div>
      <div class="value ${rankClass}">#${overall.target_rank ?? '—'}</div>
      <div class="detail">of ${overall.total_companies_mentioned || 0} companies</div>
    </div>
    <div class="score-card">
      <div class="label">LLMs Tested</div>
      <div class="value">${(a.meta?.llms_tested || []).length}</div>
      <div class="detail">${(a.weak_spots || []).length} weak spots</div>
    </div>
  `;

  // LLM table
  const llmBody = document.querySelector('#llm-table tbody');
  llmBody.innerHTML = Object.entries(a.by_llm || {}).map(([llm, d]) => {
    const rankings = a.company_rankings?.[llm] || [];
    const targetRank = rankings.find(r => r.company.toLowerCase() === audit.target_company.toLowerCase())?.rank || '—';
    return `
      <tr>
        <td><strong>${fmt.escape(llm)}</strong></td>
        <td><span style="color: var(--accent); font-weight:600;">${fmt.pct(d.visibility_score)}</span></td>
        <td class="mono">${d.mentions} / ${d.queries}</td>
        <td class="mono">#${targetRank}</td>
      </tr>
    `;
  }).join('');

  // Intent table
  const intentRows = Object.entries(a.by_intent || {})
    .sort((x, y) => y[1].visibility_score - x[1].visibility_score);
  document.querySelector('#intent-table tbody').innerHTML = intentRows.map(([intent, d]) => `
    <tr>
      <td>${fmt.escape(intent)}</td>
      <td><strong>${fmt.pct(d.visibility_score)}</strong></td>
      <td class="mono">${d.mentions}</td>
      <td class="mono">${d.queries}</td>
    </tr>
  `).join('');

  // Rankings (overall + per LLM)
  const rg = document.getElementById('rankings-grid');
  const sections = [['Overall', a.company_rankings?.overall || []]]
    .concat((a.meta?.llms_tested || []).map(llm => [llm, a.company_rankings?.[llm] || []]));
  rg.innerHTML = sections.map(([label, items]) => `
    <div class="rankings-card">
      <div class="card-header">${fmt.escape(label)} Rankings</div>
      <div class="rankings-list">
        ${items.slice(0, 20).map(item => `
          <div class="ranking-item ${item.company.toLowerCase() === audit.target_company.toLowerCase() ? 'target' : ''}">
            <div class="rank-num">${item.rank}</div>
            <div class="company-name">${fmt.escape(item.company)}</div>
            <div class="mention-count">${item.mentions}</div>
          </div>
        `).join('') || '<div class="ranking-item"><span class="muted">No mentions</span></div>'}
      </div>
    </div>
  `).join('');

  // Raw responses
  document.getElementById('raw-count').textContent = results.length;
  document.getElementById('raw-list').innerHTML = results.map(r => `
    <details style="border:1px solid var(--border); border-radius:10px; padding:12px 16px; margin-bottom:10px;">
      <summary style="cursor:pointer; display:flex; gap:12px; align-items:center;">
        <span style="font-weight:600;">${fmt.escape(r.llm)}</span>
        <span class="muted">run ${r.run_number}</span>
        <span style="flex:1;">${fmt.escape(r.query_text)}</span>
        <span style="color: ${r.target_mentioned ? 'var(--accent)' : 'var(--text-muted)'};">${r.target_mentioned ? '✓ mentioned' : '✗ not mentioned'}</span>
      </summary>
      <div style="margin-top:12px; white-space:pre-wrap; font-size:13px; color: var(--text-secondary); line-height:1.7;">${fmt.escape(r.response || '(empty response)')}</div>
      ${Object.keys(r.companies_mentioned || {}).length ? `<div style="margin-top:8px;" class="muted mono">Detected: ${Object.entries(r.companies_mentioned).map(([k,v]) => `${k}×${v}`).join(', ')}</div>` : ''}
    </details>
  `).join('');
}

// ======================================================================
// History page
// ======================================================================

async function initHistoryPage() {
  const audits = await API.listAudits();
  const tbody = document.querySelector('#history-table tbody');
  if (!audits.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="muted" style="text-align:center; padding:32px;">No audits yet — <a href="/" style="color: var(--accent);">run your first one</a>.</td></tr>';
    return;
  }
  tbody.innerHTML = audits.map(a => {
    const visibility = a.analysis?.overall?.visibility_score;
    return `
      <tr>
        <td class="mono">${a.id}</td>
        <td><a href="/results/${a.id}" style="color: var(--accent); text-decoration:none;">${fmt.escape(a.name)}</a></td>
        <td>${fmt.escape(fmt.location(a))}</td>
        <td class="muted">${a.llms.join(', ')}</td>
        <td><span class="badge badge-${a.status}">${a.status}</span></td>
        <td class="mono">${visibility != null ? fmt.pct(visibility) : '—'}</td>
        <td class="muted mono">${fmt.shortDate(a.created_at)}</td>
        <td><button class="btn btn-sm btn-danger" data-id="${a.id}">Delete</button></td>
      </tr>
    `;
  }).join('');

  tbody.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-id]');
    if (!btn) return;
    if (!confirm('Delete this audit and all its results?')) return;
    await API.deleteAudit(btn.dataset.id);
    initHistoryPage();
  });
}
