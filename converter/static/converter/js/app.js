let selectedURLs = new Set();
let crawlStartTime = null;
let timerInterval = null;

function getCSRF() {
  const el = document.querySelector('[name="csrfmiddlewaretoken"]');
  if (el) return el.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

function api(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
    body: JSON.stringify(body),
  }).then(r => r.json());
}

function startTimer(elId) {
  crawlStartTime = Date.now();
  if (timerInterval) clearInterval(timerInterval);
  const el = document.getElementById(elId);
  if (!el) return;
  timerInterval = setInterval(() => {
    if (!crawlStartTime) return clearInterval(timerInterval);
    const s = Math.floor((Date.now() - crawlStartTime) / 1000);
    el.textContent = s >= 60 ? `${Math.floor(s/60)}m ${s%60}s` : `${s}s`;
  }, 1000);
}

function toast(msg, type = 'text-bg-primary') {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast align-items-center text-white ${type} border-0 show`;
  t.innerHTML = `<div class="d-flex"><div class="toast-body">${msg}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  c.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ===== HOME PAGE =====
async function startCrawl() {
  const input = document.getElementById('urlInput');
  const btn = document.getElementById('crawlBtn');
  if (!input || !btn) return;

  const url = input.value.trim();
  if (!url) return toast('Enter a URL', 'text-bg-danger');

  btn.disabled = true;
  document.getElementById('heroSection').classList.add('d-none');
  document.getElementById('progressSection').style.setProperty('display', 'flex', 'important');
  startTimer('progressTime');

  let target = 20;
  const bar = document.getElementById('progressBarFill');
  const sim = setInterval(() => {
    if (!bar) return;
    const cur = parseFloat(bar.style.width) || 0;
    bar.style.width = Math.min(cur + (target - cur) * 0.2, 90) + '%';
    target = Math.min(target + 3, 90);
  }, 400);

  try {
    const data = await api('/api/crawl/', { url });
    clearInterval(sim);
    if (data.error) throw new Error(data.error);

    if (bar) bar.style.width = '100%';
    document.getElementById('progressCount').textContent = `${data.pages?.length || 0} pages found`;

    setTimeout(() => { window.location.href = '/workspace/'; }, 500);

  } catch (e) {
    clearInterval(sim);
    document.getElementById('heroSection').classList.remove('d-none');
    document.getElementById('progressSection').style.setProperty('display', 'none', 'important');
    btn.disabled = false;
    crawlStartTime = null;
    toast(e.message || 'Crawl failed', 'text-bg-danger');
  }
}

// ===== WORKSPACE =====
document.addEventListener('DOMContentLoaded', () => {
  // Checkbox selection
  document.querySelectorAll('.pc-checkbox').forEach(cb => {
    cb.addEventListener('change', e => {
      if (e.target.checked) selectedURLs.add(e.target.dataset.url);
      else selectedURLs.delete(e.target.dataset.url);
      updateCounts();
    });
  });

  // Arrow key navigation
  document.addEventListener('keydown', e => {
    const frame = document.getElementById('pdfFrame');
    if (!frame || !window.pagesData || frame.classList.contains('d-none')) return;
    const src = frame.src || '';
    const match = src.split('url=')[1];
    if (!match) return;
    const currentUrl = decodeURIComponent(match);
    const idx = window.pagesData.findIndex(p => p.url === currentUrl);
    if (idx === -1) return;

    if ((e.key === 'ArrowDown' || e.key === 'ArrowRight') && idx < window.pagesData.length - 1) {
      e.preventDefault();
      previewPage(window.pagesData[idx + 1].url);
    } else if ((e.key === 'ArrowUp' || e.key === 'ArrowLeft') && idx > 0) {
      e.preventDefault();
      previewPage(window.pagesData[idx - 1].url);
    }
  });

  // Focus input on home page
  const initInput = document.getElementById('urlInput');
  if (initInput) initInput.focus();
});

function selectAll(select) {
  selectedURLs.clear();
  document.querySelectorAll('.pc-checkbox').forEach(cb => {
    cb.checked = select;
    if (select) selectedURLs.add(cb.dataset.url);
  });
  updateCounts();
}

function updateCounts() {
  const countSpan = document.getElementById('selectedCount');
  const genBtn = document.getElementById('generateBtn');
  if (countSpan) countSpan.textContent = `${selectedURLs.size} selected`;
  if (genBtn) genBtn.disabled = selectedURLs.size === 0;
}

// ===== PREVIEW =====
let activePreviewURL = null;

function previewPage(url) {
  activePreviewURL = url;

  // Highlight active item
  document.querySelectorAll('.pc-page-item').forEach(el => {
    el.classList.remove('border-primary', 'bg-primary', 'bg-opacity-10');
  });
  const activeItem = document.querySelector(`.pc-page-item[data-url="${CSS.escape(url)}"]`);
  if (activeItem) activeItem.classList.add('border-primary', 'bg-primary', 'bg-opacity-10');

  // Show iframe, hide placeholder
  const frame = document.getElementById('pdfFrame');
  const placeholder = document.getElementById('previewPlaceholder');
  const dlBtn = document.getElementById('dlCurrentBtn');
  const openBtn = document.getElementById('openTabBtn');
  const videoBadge = document.getElementById('previewVideoBadge');

  if (frame && placeholder) {
    frame.src = '/api/proxy/?url=' + encodeURIComponent(url);
    frame.classList.remove('d-none');
    placeholder.classList.add('d-none');
    if (dlBtn) dlBtn.style.display = 'block';
    if (openBtn) openBtn.style.display = 'block';
  }

  // Show/hide video badge in preview header
  if (videoBadge && window.pagesData) {
    const page = window.pagesData.find(p => p.url === url);
    if (page && page.has_video) {
      videoBadge.classList.remove('d-none');
    } else {
      videoBadge.classList.add('d-none');
    }
  }
}

function openInNewTab() {
  if (activePreviewURL) window.open(activePreviewURL, '_blank');
}

// ===== PDF GENERATION =====
async function generateSelected() {
  if (selectedURLs.size === 0) return toast('Select at least one page', 'text-bg-warning');
  const btn = document.getElementById('generateBtn');
  if (btn) btn.disabled = true;

  const urls = Array.from(selectedURLs);
  const total = urls.length;
  let doneCount = 0;

  toast(`Generating ${total} PDFs...`, 'text-bg-info');

  const concurrency = 2;
  let index = 0;

  async function processNext() {
    if (index >= urls.length) return;
    const url = urls[index++];
    try {
      const data = await api('/api/generate-single/', { url });
      if (data.status === 'done' && data.pdf_url) {
        if (window.pagesData) {
          const idx = window.pagesData.findIndex(p => p.url === url);
          if (idx !== -1) window.pagesData[idx].pdf_url = data.pdf_url;
        }
        const b = document.querySelector(`.status-badge[data-url="${CSS.escape(url)}"]`);
        if (b) b.classList.remove('d-none');
        doneCount++;
      } else {
        const b = document.querySelector(`.status-badge-fail[data-url="${CSS.escape(url)}"]`);
        if (b) b.classList.remove('d-none');
      }
    } catch {
      const b = document.querySelector(`.status-badge-fail[data-url="${CSS.escape(url)}"]`);
      if (b) b.classList.remove('d-none');
    }
    await processNext();
  }

  const workers = [];
  for (let i = 0; i < Math.min(concurrency, urls.length); i++) workers.push(processNext());
  await Promise.all(workers);

  const dBar = document.getElementById('downloadBar');
  if (dBar) {
    dBar.classList.remove('d-none');
    document.getElementById('downloadSummary').textContent = `✓ Generated ${doneCount} of ${total} PDFs`;
  }
  toast(`Done! Generated ${doneCount} PDFs`, 'text-bg-success');
  if (btn) btn.disabled = false;
}

// ===== DOWNLOAD CURRENT =====
async function downloadCurrent() {
  if (!activePreviewURL) return;
  let page = window.pagesData?.find(p => p.url === activePreviewURL);
  if (page && page.pdf_url) {
    const a = document.createElement('a'); a.href = page.pdf_url; a.download = ''; a.click();
    return;
  }
  toast('Generating PDF...', 'text-bg-info');
  try {
    const data = await api('/api/generate-single/', { url: activePreviewURL });
    if (data.status === 'done' && data.pdf_url) {
      if (page) page.pdf_url = data.pdf_url;
      const b = document.querySelector(`.status-badge[data-url="${CSS.escape(activePreviewURL)}"]`);
      if (b) b.classList.remove('d-none');
      const a = document.createElement('a'); a.href = data.pdf_url; a.download = ''; a.click();
      toast('Downloaded successfully', 'text-bg-success');
    } else {
      toast('Generation failed', 'text-bg-danger');
    }
  } catch {
    toast('Generation failed', 'text-bg-danger');
  }
}
