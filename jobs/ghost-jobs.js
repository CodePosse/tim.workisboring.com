/*
 * Ghost Jobs demo widget — stands in for what the browser extension's content script would inject.
 *
 * Each snapshot page sets window.GhostJobsDemo before loading this file:
 *   source, company, title, location   job identity (used for the "Add to our DB" record)
 *   titleSelector                      CSS selector for the job title (falls back to matching `title` text)
 *   areaText                           text the highlighted job area must contain (walks up from the title)
 *   state                              starting state: 'sunshine' | 'ghost' | 'zombie'
 *   facts                              { currentListing, firstSeen, cycles, freshness, applicants }
 *
 * Add #ghostjobs to the page URL to open the report on load.
 */
(function () {
  const cfg = window.GhostJobsDemo || {};
  const facts = cfg.facts || {};
  const source = cfg.source || 'Job board';
  const storageKey = name => 'ghostjobs-demo-' + name + ':' + source.toLowerCase();

  const states = [
    {key: 'sunshine', icon: '☀️', title: 'Fresh lead / Sunshine', desc: 'Too new for meaningful negative history.', color: '#d97706', bg: '#fff7ed'},
    {key: 'ghost', icon: '👻', title: 'Ghost-job warning', desc: 'Listing has aged without strong evidence of active hiring or candidate response.', color: '#6b4eff', bg: '#f5f3ff'},
    {key: 'zombie', icon: '🧟', title: 'Zombie-job warning', desc: 'This role appears to have returned repeatedly across multiple posting cycles.', color: '#b42318', bg: '#fff1f0'}];
  const sites = ['LinkedIn', 'Indeed', 'Dice', 'Ladders', 'Company careers'].filter(site => site !== source);

  const esc = value => String(value).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
  const store = {
    get(name) { try { return localStorage.getItem(storageKey(name)); } catch (e) { return null; } },
    set(name, value) { try { localStorage.setItem(storageKey(name), value); } catch (e) { /* storage unavailable */ } }
  };

  document.body.insertAdjacentHTML('beforeend', `
<button class="ghostjobs-trigger" id="ghostJobsTrigger" type="button" data-state="sunshine" aria-label="Open Ghost Jobs job freshness report" aria-controls="ghostJobsPanel" aria-expanded="false" title="Ghost Jobs"><span class="ghostjobs-trigger-icon" id="ghostJobsTriggerIcon" aria-hidden="true">☀️</span></button>
<aside class="ghostjobs-panel" id="ghostJobsPanel" aria-label="Ghost Jobs report">
  <div class="ghostjobs-head"><div class="ghostjobs-logo" id="gjLogo" aria-hidden="true">☀️</div><div><h2>Ghost Jobs</h2><p>Community job-posting freshness &amp; repetition signal</p></div></div>
  <div class="ghostjobs-body">
    <div class="gj-status" id="gjStatus"><strong></strong><span></span></div>
    <dl class="gj-grid">
      <dt>Current listing</dt><dd>${esc(facts.currentListing || 'Posted recently')}</dd>
      <dt>Likely first seen</dt><dd>${esc(facts.firstSeen || 'Unknown')} <span class="gj-muted">(demo history)</span></dd>
      <dt>Observed cycles</dt><dd>${esc(facts.cycles || '1 posting cycle')}</dd>
      <dt>Freshness</dt><dd id="gjFreshness">${esc(facts.freshness || 'Unknown')}</dd>
      <dt>Applicant pressure</dt><dd>${esc(facts.applicants || 'Not reported')}</dd>
      <dt>Community reports</dt><dd id="gjReports">0 ghosted reports</dd>
    </dl>
    <div class="gj-sites-label">Likely also seen on</div>
    <div class="gj-sites">${sites.map(site => `<span class="gj-chip">${esc(site)}</span>`).join('')}</div>
    <div class="gj-note"><strong>Why this matters:</strong> a repost date alone can make an old requisition look new. Ghost Jobs would preserve a normalized fingerprint of the company, title, location and description so later reposts can be recognized as the same underlying role.</div>
    <div class="gj-actions"><button class="gj-btn" id="gjAdd" type="button">Add to our DB</button><button class="gj-btn ghosted" id="gjGhosted" type="button">I've been ghosted</button><button class="gj-btn secondary" id="gjCycle" type="button">Demo next state</button><button class="gj-btn secondary" id="gjClose" type="button">Close</button></div>
    <div class="gj-small">Prototype only: buttons store demo interactions locally in this browser. A production extension would send a normalized job record and source URL to the Ghost Jobs API.</div>
  </div>
</aside><div class="ghostjobs-toast" id="ghostJobsToast" role="status" aria-live="polite"></div>`);

  const trigger = document.getElementById('ghostJobsTrigger'), panel = document.getElementById('ghostJobsPanel'), toast = document.getElementById('ghostJobsToast');
  let idx = Math.max(0, states.findIndex(s => s.key === cfg.state)), highlighted = null, toastTimer = null;
  let reports = Number(store.get('reports') || 0);

  function findJobArea() {
    const title = cfg.titleSelector
      ? document.querySelector(cfg.titleSelector)
      : [...document.querySelectorAll('p,h1,h2,h3,h4,h5')].find(el => (el.textContent || '').includes(cfg.title));
    if (!title) return document.querySelector('main') || document.body;
    if (cfg.areaText) {
      let el = title;
      for (let i = 0; i < 6 && el.parentElement; i++, el = el.parentElement) {
        if ((el.textContent || '').includes(cfg.areaText)) return el;
      }
    }
    return title.parentElement;
  }

  function applyState() {
    const s = states[idx];
    document.getElementById('ghostJobsTriggerIcon').textContent = s.icon;
    trigger.dataset.state = s.key;
    document.getElementById('gjLogo').textContent = s.icon;
    const st = document.getElementById('gjStatus');
    st.querySelector('strong').textContent = s.title;
    st.querySelector('span').textContent = s.desc;
    st.style.borderColor = s.color;
    st.style.background = s.bg;
    if (highlighted) highlighted.style.setProperty('--gj-highlight', s.color);
  }

  function mark() { highlighted = findJobArea(); highlighted.classList.add('gj-highlight'); applyState(); }
  function unmark() { if (highlighted) { highlighted.classList.remove('gj-highlight'); highlighted.style.removeProperty('--gj-highlight'); } }
  function showToast(msg) { toast.textContent = msg; toast.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('show'), 2200); }
  function updateReports() { document.getElementById('gjReports').textContent = reports + ' ghosted report' + (reports === 1 ? '' : 's'); }

  function setOpen(open) {
    panel.classList.toggle('open', open);
    trigger.setAttribute('aria-expanded', String(open));
    if (open) mark(); else unmark();
  }

  trigger.addEventListener('click', () => setOpen(!panel.classList.contains('open')));
  document.getElementById('gjClose').addEventListener('click', () => { setOpen(false); trigger.focus(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && panel.classList.contains('open')) { setOpen(false); trigger.focus(); } });
  document.getElementById('gjCycle').addEventListener('click', () => { idx = (idx + 1) % states.length; applyState(); showToast('Demo status changed to ' + states[idx].title); });
  document.getElementById('gjAdd').addEventListener('click', function () {
    const record = {company: cfg.company, title: cfg.title, location: cfg.location, source: source, seenAt: new Date().toISOString(), url: location.href};
    store.set('job', JSON.stringify(record));
    this.textContent = 'Added ✓';
    this.disabled = true;
    showToast('Saved to the local Ghost Jobs demo log');
  });
  document.getElementById('gjGhosted').addEventListener('click', () => { reports++; store.set('reports', reports); updateReports(); showToast('Ghosted report recorded locally'); });

  updateReports();
  applyState();
  if (location.hash === '#ghostjobs') setOpen(true);
})();
