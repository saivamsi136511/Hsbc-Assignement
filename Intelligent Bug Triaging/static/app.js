/* ============================================================
   BugTriager — Frontend Application JavaScript
   ============================================================ */
'use strict';

const state = {
  tickets: [], stats: null,
  activeFilter: { view: 'all', category: null, severity: null, status: null },
  selectedTicket: null, searchQuery: '', searchDebounce: null,
};

const API = {
  base: '/api',
  async get(path) {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(this.base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const json = await r.json();
    if (!r.ok) throw new Error(json.error || r.statusText);
    return json;
  },
  async patch(path, body) {
    const r = await fetch(this.base + path, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};

function timeAgo(iso) {
  const diff = Date.now() - new Date(iso + 'Z').getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60)    return 'just now';
  if (s < 3600)  return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}

function severityClass(sev) {
  return { Critical: 'sev-critical', High: 'sev-high', Medium: 'sev-medium', Low: 'sev-low' }[sev] || '';
}

function statusClass(status) {
  return 'status-' + (status || 'Open').replace(/\s+/g, '-');
}

function categoryIcon(cat) {
  const icons = { UI: '🎨', Backend: '⚙️', Database: '🗄️', Authentication: '🔐', Security: '🛡️', Performance: '⚡', Network: '🌐', Mobile: '📱', Infrastructure: '🏗️', Unknown: '❓' };
  return icons[cat] || '📌';
}

function escapeHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showToast(message, type = 'info', duration = 4000) {
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${icons[type]||'ℹ️'}</span><span>${escapeHtml(message)}</span>`;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => {
    el.style.cssText = 'opacity:0;transform:translateX(20px);transition:all 0.3s ease';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

function setTextContent(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

async function loadStats() {
  try {
    const stats = await API.get('/stats');
    state.stats = stats;
    const bySev = stats.by_severity || {};
    const byStatus = stats.by_status || {};
    const byPrio = stats.by_priority || {};
    setTextContent('statTotalVal',    stats.total     || 0);
    setTextContent('statCriticalVal', bySev.Critical  || 0);
    setTextContent('statHighVal',     bySev.High      || 0);
    setTextContent('statMediumVal',   bySev.Medium    || 0);
    setTextContent('statLowVal',      bySev.Low       || 0);
    setTextContent('statP1Val',       byPrio.P1       || 0);
    setTextContent('countAll',        stats.total     || 0);
    setTextContent('countOpen',       byStatus.Open   || 0);
    setTextContent('countCritical',   bySev.Critical  || 0);
    setTextContent('countInProgress', byStatus['In Progress'] || 0);
  } catch (e) { console.error('Stats error:', e); }
}

async function loadTickets() {
  const f = state.activeFilter;
  let url = '/bugs?limit=200';
  if (f.category) url += `&category=${encodeURIComponent(f.category)}`;
  if (f.severity) url += `&severity=${encodeURIComponent(f.severity)}`;
  if (f.view === 'open')        url += '&status=Open';
  else if (f.view === 'critical') url += '&severity=Critical';
  else if (f.view === 'in-progress') url += '&status=In+Progress';
  if (f.status) url += `&status=${encodeURIComponent(f.status)}`;
  try {
    const data = await API.get(url);
    state.tickets = data.tickets || [];
    renderTicketList(state.tickets);
  } catch (e) { showToast('Failed to load tickets: ' + e.message, 'error'); }
}

function renderTicketList(tickets) {
  const list  = document.getElementById('ticketList');
  const empty = document.getElementById('emptyState');
  const badge = document.getElementById('ticketCountBadge');
  badge.textContent = `${tickets.length} ticket${tickets.length !== 1 ? 's' : ''}`;
  if (!tickets.length) {
    list.innerHTML = '';
    list.style.display = 'none';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  list.style.display = '';
  list.innerHTML = tickets.map(renderTicketCard).join('');
  list.querySelectorAll('.ticket-card').forEach(card => {
    card.addEventListener('click', () => {
      const t = tickets.find(t => t.id === parseInt(card.dataset.id));
      if (t) openDetail(t);
    });
  });
}

function renderTicketCard(t) {
  const sevClass  = severityClass(t.severity);
  const statClass = statusClass(t.status);
  const selected  = state.selectedTicket && state.selectedTicket.id === t.id ? ' selected' : '';
  return `
  <div class="ticket-card ${sevClass}${selected}" data-id="${t.id}" id="card-${t.id}">
    <div class="ticket-priority">
      <span class="priority-badge prio-${escapeHtml(t.priority)}">${escapeHtml(t.priority)}</span>
    </div>
    <div class="ticket-center">
      <div class="ticket-title-row">
        <span class="ticket-bug-id">${escapeHtml(t.bug_id)}</span>
        <span class="ticket-title">${escapeHtml(t.title)}</span>
      </div>
      <div class="ticket-meta">
        <span class="ticket-category-badge">${categoryIcon(t.category)} ${escapeHtml(t.category)}</span>
        <span class="ticket-severity-badge sev-badge-${escapeHtml(t.severity)}">${escapeHtml(t.severity)}</span>
        <span class="ticket-team">👥 ${escapeHtml(t.assigned_team)}</span>
        <span class="ticket-time">🕐 ${timeAgo(t.submitted_at)}</span>
      </div>
    </div>
    <div class="ticket-right">
      <span class="ticket-status-badge ${statClass}">${escapeHtml(t.status)}</span>
      <span class="ticket-urgency">
        <span class="urgency-dot urgency-${escapeHtml(t.urgency_level)}"></span>
        Urgency: ${t.urgency_score}
      </span>
    </div>
  </div>`;
}

function openDetail(ticket) {
  state.selectedTicket = ticket;
  document.querySelectorAll('.ticket-card').forEach(c => c.classList.remove('selected'));
  const card = document.getElementById(`card-${ticket.id}`);
  if (card) card.classList.add('selected');
  document.getElementById('detailBugId').textContent = ticket.bug_id;
  const sb = document.getElementById('detailStatusBadge');
  sb.textContent = ticket.status;
  sb.className = `detail-status-badge ${statusClass(ticket.status)}`;
  document.getElementById('detailStatusSelect').value = ticket.status;
  document.getElementById('detailBody').innerHTML = buildDetailBody(ticket);
  document.getElementById('detailPanel').classList.add('open');
  document.getElementById('mainContent').classList.add('panel-open');
  document.getElementById('detailOverlay').style.display = 'block';
}

function closeDetail() {
  state.selectedTicket = null;
  document.getElementById('detailPanel').classList.remove('open');
  document.getElementById('mainContent').classList.remove('panel-open');
  document.getElementById('detailOverlay').style.display = 'none';
  document.querySelectorAll('.ticket-card').forEach(c => c.classList.remove('selected'));
}

function buildDetailBody(t) {
  const dupWarning = t.duplicate_of
    ? `<div class="detail-duplicate-warning">⚠️ Marked as duplicate of ticket #${t.duplicate_of}</div>` : '';
  const uf = Math.min(100, t.urgency_score || 0);
  const cf = Math.min(100, t.confidence || 0);
  return `
    ${dupWarning}
    <div class="detail-section">
      <div class="detail-title">${escapeHtml(t.title)}</div>
      <div class="detail-description">${escapeHtml(t.description)}</div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Classification</div>
      <div class="detail-chips">
        <span class="detail-chip chip-category">${categoryIcon(t.category)} ${escapeHtml(t.category)}</span>
        <span class="detail-chip chip-team">👥 ${escapeHtml(t.assigned_team)}</span>
      </div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Scores</div>
      <div class="detail-grid">
        <div class="detail-field">
          <div class="detail-field-label">Severity</div>
          <div class="detail-field-value"><span class="ticket-severity-badge sev-badge-${escapeHtml(t.severity)}">${escapeHtml(t.severity)}</span></div>
        </div>
        <div class="detail-field">
          <div class="detail-field-label">Priority</div>
          <div class="detail-field-value"><span class="priority-badge prio-${escapeHtml(t.priority)}">${escapeHtml(t.priority)}</span></div>
        </div>
        <div class="detail-field">
          <div class="detail-field-label">AI Confidence</div>
          <div class="detail-field-value">${cf}%</div>
          <div class="confidence-bar"><div class="confidence-fill" style="width:${cf}%"></div></div>
        </div>
        <div class="detail-field">
          <div class="detail-field-label">Urgency Score</div>
          <div class="urgency-meter">
            <span class="detail-field-value">${uf}</span>
            <div class="urgency-meter-bar"><div class="urgency-meter-fill urg-${escapeHtml(t.urgency_level)}" style="width:${uf}%"></div></div>
          </div>
        </div>
      </div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">AI Summary</div>
      <div class="detail-summary">${escapeHtml(t.summary || 'No summary available.')}</div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">💡 Suggested Fix</div>
      <div class="detail-fix">${escapeHtml(t.suggested_fix || 'No suggestion available.')}</div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">Metadata</div>
      <div class="detail-grid">
        <div class="detail-field">
          <div class="detail-field-label">Submitted by</div>
          <div class="detail-field-value">${escapeHtml(t.submitter||'anonymous')}</div>
        </div>
        <div class="detail-field">
          <div class="detail-field-label">Submitted at</div>
          <div class="detail-field-value">${timeAgo(t.submitted_at)}</div>
        </div>
        <div class="detail-field">
          <div class="detail-field-label">Analysis</div>
          <div class="detail-field-value"><span class="source-badge">🤖 ${escapeHtml(t.analysis_source||'heuristic')}</span></div>
        </div>
        <div class="detail-field">
          <div class="detail-field-label">Urgency</div>
          <div class="detail-field-value"><span class="urgency-dot urgency-${escapeHtml(t.urgency_level)}"></span> ${escapeHtml(t.urgency_level)}</div>
        </div>
      </div>
    </div>`;
}

async function saveDetailStatus() {
  if (!state.selectedTicket) return;
  const newStatus = document.getElementById('detailStatusSelect').value;
  try {
    const updated = await API.patch(`/bugs/${state.selectedTicket.id}`, { status: newStatus });
    state.selectedTicket = updated;
    await Promise.all([loadTickets(), loadStats()]);
    openDetail(updated);
    showToast(`Status updated to "${newStatus}"`, 'success');
  } catch (e) { showToast('Failed to update: ' + e.message, 'error'); }
}

function openSubmitModal() {
  document.getElementById('bugTitle').value       = '';
  document.getElementById('bugDescription').value = '';
  document.getElementById('bugSubmitter').value   = '';
  document.getElementById('titleCharCount').textContent = '0';
  document.getElementById('descCharCount').textContent  = '0';
  document.getElementById('submitModal').classList.add('active');
  setTimeout(() => document.getElementById('bugTitle').focus(), 50);
}

function closeSubmitModal() {
  document.getElementById('submitModal').classList.remove('active');
}

async function submitBugReport() {
  const title       = document.getElementById('bugTitle').value.trim();
  const description = document.getElementById('bugDescription').value.trim();
  const submitter   = document.getElementById('bugSubmitter').value.trim() || 'anonymous';
  if (!title)       { showToast('Please enter a bug title', 'warning'); return; }
  if (!description) { showToast('Please describe the bug', 'warning'); return; }
  const submitBtn = document.getElementById('modalSubmitBtn');
  const btnText   = submitBtn.querySelector('.btn-text');
  const btnLoader = submitBtn.querySelector('.btn-loader');
  submitBtn.disabled = true;
  btnText.style.display  = 'none';
  btnLoader.style.display = '';
  try {
    const result = await API.post('/bugs', { title, description, submitter });
    closeSubmitModal();
    showResultModal(result);
    await Promise.all([loadTickets(), loadStats()]);
  } catch (e) {
    showToast('Submission failed: ' + e.message, 'error');
  } finally {
    submitBtn.disabled = false;
    btnText.style.display  = '';
    btnLoader.style.display = 'none';
  }
}

let _lastResult = null;

function showResultModal(result) {
  _lastResult = result;
  const t = result.ticket;
  const dupBanner = result.is_duplicate
    ? `<div class="duplicate-warning-banner">⚠️ <div><strong>Possible Duplicate Detected</strong><br/>This ticket resembles <strong>${escapeHtml(result.duplicate_of?.bug_id||'')}</strong>. It has been marked accordingly.</div></div>`
    : '';
  document.getElementById('resultBody').innerHTML = `
    ${dupBanner}
    <div class="result-grid">
      <div class="result-field"><div class="result-field-label">Ticket ID</div><div class="result-field-value" style="font-family:monospace">${escapeHtml(t.bug_id)}</div></div>
      <div class="result-field"><div class="result-field-label">Category</div><div class="result-field-value">${categoryIcon(t.category)} ${escapeHtml(t.category)}</div></div>
      <div class="result-field"><div class="result-field-label">Severity</div><div class="result-field-value"><span class="ticket-severity-badge sev-badge-${escapeHtml(t.severity)}">${escapeHtml(t.severity)}</span></div></div>
      <div class="result-field"><div class="result-field-label">Priority</div><div class="result-field-value"><span class="priority-badge prio-${escapeHtml(t.priority)}">${escapeHtml(t.priority)}</span></div></div>
      <div class="result-field"><div class="result-field-label">Assigned Team</div><div class="result-field-value">👥 ${escapeHtml(t.assigned_team)}</div></div>
      <div class="result-field"><div class="result-field-label">AI Confidence</div><div class="result-field-value">${t.confidence}%</div></div>
      <div class="result-field"><div class="result-field-label">Urgency</div><div class="result-field-value"><span class="urgency-dot urgency-${escapeHtml(t.urgency_level)}"></span> ${escapeHtml(t.urgency_level)} (${t.urgency_score}/100)</div></div>
      <div class="result-field"><div class="result-field-label">Analysis</div><div class="result-field-value" style="font-size:0.78rem">🤖 ${escapeHtml(t.analysis_source)}</div></div>
    </div>
    <div><div class="result-label">📝 AI Summary</div><div class="result-summary">${escapeHtml(t.summary||'No summary generated.')}</div></div>
    <div><div class="result-label">💡 Suggested Fix</div><div class="result-fix">${escapeHtml(t.suggested_fix||'No suggestion.')}</div></div>`;
  document.getElementById('resultModal').classList.add('active');
}

function closeResultModal() {
  document.getElementById('resultModal').classList.remove('active');
  _lastResult = null;
}

function viewLastTicket() {
  closeResultModal();
  if (_lastResult) {
    const t = state.tickets.find(x => x.id === _lastResult.ticket.id);
    if (t) openDetail(t); else openDetail(_lastResult.ticket);
  }
}

function handleSearch(query) {
  state.searchQuery = query;
  clearTimeout(state.searchDebounce);
  if (!query.trim()) { loadTickets(); return; }
  state.searchDebounce = setTimeout(async () => {
    try {
      const data = await API.get(`/bugs/search?q=${encodeURIComponent(query)}`);
      state.tickets = data.tickets || [];
      renderTicketList(state.tickets);
      document.getElementById('toolbarTitle').textContent = `Search: "${query}"`;
      document.getElementById('ticketCountBadge').textContent = `${state.tickets.length} result${state.tickets.length!==1?'s':''}`;
    } catch (e) { showToast('Search failed: ' + e.message, 'error'); }
  }, 300);
}

function activateSidebarItem(item) {
  document.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
  item.classList.add('active');
}

function setSidebarView(view, label) {
  state.activeFilter = { view, category: null, severity: null, status: null };
  document.getElementById('filterCategory').value = '';
  document.getElementById('filterSeverity').value = '';
  document.getElementById('filterStatus').value   = '';
  document.getElementById('globalSearch').value   = '';
  document.getElementById('toolbarTitle').textContent = label;
  loadTickets();
}

document.addEventListener('DOMContentLoaded', () => {
  loadTickets();
  loadStats();

  document.getElementById('newBugBtn').addEventListener('click', openSubmitModal);

  document.getElementById('viewAll').addEventListener('click', function() { activateSidebarItem(this); setSidebarView('all', 'All Tickets'); });
  document.getElementById('viewOpen').addEventListener('click', function() { activateSidebarItem(this); setSidebarView('open', 'Open Tickets'); });
  document.getElementById('viewCritical').addEventListener('click', function() { activateSidebarItem(this); setSidebarView('critical', 'Critical Tickets'); });
  document.getElementById('viewInProgress').addEventListener('click', function() { activateSidebarItem(this); setSidebarView('in-progress', 'In Progress'); });

  document.querySelectorAll('[data-category]').forEach(btn => {
    btn.addEventListener('click', function() {
      activateSidebarItem(this);
      const cat = this.dataset.category;
      state.activeFilter = { view: 'category', category: cat, severity: null, status: null };
      document.getElementById('filterCategory').value = cat;
      document.getElementById('filterSeverity').value = '';
      document.getElementById('filterStatus').value   = '';
      document.getElementById('globalSearch').value   = '';
      document.getElementById('toolbarTitle').textContent = cat + ' Tickets';
      loadTickets();
    });
  });

  ['filterCategory','filterSeverity','filterStatus'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      state.activeFilter.category = document.getElementById('filterCategory').value || null;
      state.activeFilter.severity = document.getElementById('filterSeverity').value || null;
      state.activeFilter.status   = document.getElementById('filterStatus').value   || null;
      loadTickets();
    });
  });

  document.getElementById('globalSearch').addEventListener('input', e => handleSearch(e.target.value));

  document.getElementById('refreshBtn').addEventListener('click', async () => {
    await Promise.all([loadTickets(), loadStats()]);
    showToast('Refreshed', 'info', 1500);
  });

  document.getElementById('detailClose').addEventListener('click', closeDetail);
  document.getElementById('detailOverlay').addEventListener('click', closeDetail);
  document.getElementById('detailSaveBtn').addEventListener('click', saveDetailStatus);

  document.getElementById('modalClose').addEventListener('click', closeSubmitModal);
  document.getElementById('modalCancelBtn').addEventListener('click', closeSubmitModal);
  document.getElementById('modalSubmitBtn').addEventListener('click', submitBugReport);
  document.getElementById('submitModal').addEventListener('click', e => { if (e.target === document.getElementById('submitModal')) closeSubmitModal(); });

  document.getElementById('bugTitle').addEventListener('input', e => { document.getElementById('titleCharCount').textContent = e.target.value.length; });
  document.getElementById('bugDescription').addEventListener('input', e => { document.getElementById('descCharCount').textContent = e.target.value.length; });
  document.getElementById('bugTitle').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('bugDescription').focus(); });
  document.getElementById('bugDescription').addEventListener('keydown', e => { if (e.key === 'Enter' && e.ctrlKey) submitBugReport(); });

  document.getElementById('resultClose').addEventListener('click', closeResultModal);
  document.getElementById('resultDoneBtn').addEventListener('click', closeResultModal);
  document.getElementById('resultViewBtn').addEventListener('click', viewLastTicket);
  document.getElementById('resultModal').addEventListener('click', e => { if (e.target === document.getElementById('resultModal')) closeResultModal(); });

  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); document.getElementById('globalSearch').focus(); }
    if (e.key === 'Escape') { closeDetail(); closeSubmitModal(); closeResultModal(); }
    if (e.key === 'n' && !e.metaKey && !e.ctrlKey && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) openSubmitModal();
  });

  setInterval(() => { loadTickets(); loadStats(); }, 30000);
});
