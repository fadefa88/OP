const els = {
  form: document.querySelector('#reader-picker-form'),
  volumeSelect: document.querySelector('#volume-select'),
  chapterSelect: document.querySelector('#chapter-select'),
  chapterGrid: document.querySelector('#chapter-grid'),
  chapterSearch: document.querySelector('#chapter-search'),
  libraryStats: document.querySelector('#library-stats'),
  volumeTitle: document.querySelector('#volume-title'),
  latestChapter: document.querySelector('#latest-chapter'),
  continueReading: document.querySelector('#continue-reading'),
  copyrightLabel: document.querySelector('#copyright-label'),
  lastUpdatedLabel: document.querySelector('#last-updated-label')
};

const state = {
  manifest: null,
  series: null,
  volume: null,
  search: '',
  selectedChapterId: null
};

function isIosLike() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function setupHomeVideo() {
  const video = document.querySelector('.home-backdrop-video');
  if (!video) return;

  // The desktop background is decorative. Keep it visible even while play() is being negotiated.
  // On iPhone we still hide it if autoplay is blocked, to avoid the native play overlay.

  const isCoarse = window.matchMedia('(hover: none), (pointer: coarse)').matches;
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  video.muted = true;
  video.defaultMuted = true;
  video.loop = true;
  video.autoplay = true;
  video.playsInline = true;
  video.controls = false;
  video.disablePictureInPicture = true;
  video.setAttribute('muted', '');
  video.setAttribute('playsinline', '');
  video.setAttribute('webkit-playsinline', '');
  video.setAttribute('autoplay', '');
  video.setAttribute('loop', '');
  video.removeAttribute('controls');

  const markPlaying = () => {
    document.body.classList.add('video-playing');
    document.body.classList.remove('video-autoplay-blocked');
  };

  const markBlocked = () => {
    document.body.classList.add('video-autoplay-blocked');
    if (isIosLike()) {
      document.body.classList.remove('video-playing');
    } else {
      // Muted autoplay should work on desktop, but if the browser delays it, keep the animated background visible.
      document.body.classList.add('video-playing');
    }
  };

  const keepLooping = () => {
    if (!Number.isFinite(video.duration) || video.duration <= 0) return;
    if (video.currentTime >= video.duration - 0.12) {
      video.currentTime = 0.001;
      const replay = video.play();
      if (replay?.catch) replay.catch(markBlocked);
    }
  };

  const tryPlay = () => {
    if (prefersReducedMotion) {
      markBlocked();
      return;
    }

    video.muted = true;
    video.defaultMuted = true;
    video.loop = true;
    video.autoplay = true;
    video.playsInline = true;
    video.setAttribute('muted', '');
    video.setAttribute('loop', '');
    video.setAttribute('autoplay', '');
    video.setAttribute('playsinline', '');
    video.setAttribute('webkit-playsinline', '');

    if (video.readyState === 0) video.load();

    const promise = video.play();
    if (promise?.then) {
      promise.then(markPlaying).catch(markBlocked);
    } else if (!video.paused) {
      markPlaying();
    }
  };

  video.addEventListener('playing', markPlaying);
  video.addEventListener('loadedmetadata', () => {
    if (!Number.isFinite(video.duration) || video.duration <= 0) return;
    if (video.currentTime === 0) video.currentTime = 0.001;
    tryPlay();
  }, { once: true });
  video.addEventListener('canplay', tryPlay, { once: true });
  video.addEventListener('timeupdate', keepLooping);
  video.addEventListener('ended', () => {
    video.currentTime = 0;
    tryPlay();
  });
  video.addEventListener('pause', () => {
    if (!document.hidden && !isCoarse) window.setTimeout(tryPlay, 250);
  });
  video.addEventListener('stalled', () => window.setTimeout(tryPlay, 700));

  window.addEventListener('load', tryPlay, { once: true });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) tryPlay();
  });

  ['touchstart', 'pointerdown', 'click'].forEach((eventName) => {
    document.addEventListener(eventName, tryPlay, { once: true, passive: true });
  });

  tryPlay();
}

async function loadManifest() {
  // Fast path: the importers keep this combined manifest updated.
  // Avoid a full R2 bucket scan on normal page loads, otherwise the homepage waits too long before filling menus.
  const response = await fetch('/content/manifest.json', { headers: { accept: 'application/json' }, cache: 'no-cache' });
  if (!response.ok) throw new Error('Archivio non disponibile');
  return response.json();
}

function naturalNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function getChapters(series) {
  return [...(series?.chapters || [])].sort((a, b) => naturalNumber(a.number) - naturalNumber(b.number));
}

function getVolumes(series) {
  const volumes = new Map();
  getChapters(series).forEach((chapter) => {
    const volume = chapter.volume ?? 'speciali';
    if (!volumes.has(volume)) volumes.set(volume, []);
    volumes.get(volume).push(chapter);
  });

  return [...volumes.entries()].sort(([a], [b]) => {
    const na = Number(a);
    const nb = Number(b);
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
    return String(a).localeCompare(String(b), 'it');
  });
}

function chapterHref(seriesId, chapterId, page = 1) {
  const params = new URLSearchParams({ series: seriesId, chapter: chapterId, page: String(page) });
  return `/reader.html?${params.toString()}`;
}

function getLastReading() {
  try {
    return JSON.parse(localStorage.getItem('reader.last') || 'null');
  } catch {
    return null;
  }
}

function option(label, value, selected = false) {
  const el = document.createElement('option');
  el.value = value;
  el.textContent = label;
  el.selected = selected;
  return el;
}

function renderVolumeSelect() {
  const volumes = getVolumes(state.series);
  els.volumeSelect.innerHTML = '';

  volumes.forEach(([volume]) => {
    els.volumeSelect.appendChild(option(`Volume ${volume}`, String(volume), String(volume) === String(state.volume)));
  });

  if (!volumes.some(([volume]) => String(volume) === String(state.volume))) {
    state.volume = volumes.at(-1)?.[0] ?? null;
    if (state.volume !== null) els.volumeSelect.value = String(state.volume);
  }
}

function getVisibleChapters() {
  const query = state.search.trim().toLowerCase();

  if (query) {
    return getChapters(state.series).filter((chapter) => {
      const haystack = [chapter.title, chapter.number, chapter.volume, chapter.id]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  }

  return getChapters(state.series).filter((chapter) => String(chapter.volume ?? 'speciali') === String(state.volume));
}

function renderChapterSelect() {
  const chapters = getVisibleChapters();
  els.chapterSelect.innerHTML = '';

  const preferredId = state.selectedChapterId && chapters.some((chapter) => chapter.id === state.selectedChapterId)
    ? state.selectedChapterId
    : chapters.at(-1)?.id;

  chapters.forEach((chapter) => {
    const label = `Cap. ${chapter.number ?? chapter.id}`;
    els.chapterSelect.appendChild(option(label, chapter.id, chapter.id === preferredId));
  });

  if (preferredId) {
    els.chapterSelect.value = preferredId;
    state.selectedChapterId = preferredId;
  }
}

function renderChapterGrid() {
  const chapters = getVisibleChapters();
  els.chapterGrid.innerHTML = '';

  if (!chapters.length) {
    els.chapterGrid.innerHTML = `
      <article class="empty-state">
        <h3>Nessun capitolo trovato</h3>
        <p>Prova a cambiare volume oppure svuotare la ricerca.</p>
      </article>
    `;
    return;
  }

  const fragment = document.createDocumentFragment();
  chapters.forEach((chapter) => {
    const link = document.createElement('a');
    link.className = 'chapter-card-link';
    link.href = chapterHref(state.series.id, chapter.id);
    link.innerHTML = `
      <span class="chapter-number">${chapter.number ?? chapter.id}</span>
      <span class="chapter-meta">
        <strong>${chapter.title || `Capitolo ${chapter.number}`}</strong>
        <small>Volume ${chapter.volume ?? 'speciali'}</small>
      </span>
      <span aria-hidden="true">›</span>
    `;
    fragment.appendChild(link);
  });

  els.chapterGrid.appendChild(fragment);
}

function renderStats() {
  els.libraryStats.textContent = '';
  els.libraryStats.hidden = true;
  els.volumeTitle.textContent = state.search ? 'Risultati ricerca' : `Volume ${state.volume}`;
}

function renderQuickLinks() {
  const chapters = getChapters(state.series);
  const latest = chapters.at(-1);
  if (!latest) return;

  const latestNumber = latest.number ?? latest.id;
  const latestText = `Ultimo capitolo ${latestNumber} appena uscito!`;
  els.latestChapter.href = chapterHref(state.series.id, latest.id);
  els.latestChapter.textContent = latestText;
  els.continueReading.href = chapterHref(state.series.id, latest.id);
  els.continueReading.textContent = latestText;
}

function formatItalianDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  return `${day}/${month}/${year}`;
}

function renderFooter() {
  const startYear = 2026;
  const currentYear = new Date().getFullYear();
  els.copyrightLabel.textContent = currentYear <= startYear ? `© LDF ${startYear}` : `© LDF ${startYear}-${currentYear}`;

  const lastUpdated = state.manifest?.lastUpdatedAt || state.manifest?.generatedAt || state.series?.lastUpdatedAt || state.series?.generatedAt;
  const formatted = formatItalianDate(lastUpdated);
  els.lastUpdatedLabel.textContent = formatted ? `last updated ${formatted}` : 'last updated --/--/----';
}

function renderAll() {
  renderVolumeSelect();
  renderChapterSelect();
  renderChapterGrid();
  renderStats();
  renderQuickLinks();
  renderFooter();
}

function selectDefaultState(manifest) {
  const firstSeries = manifest.series[0];
  state.series = firstSeries;

  const chapters = getChapters(state.series);
  const latestNumber = Number(state.series?.latestChapter);
  const latestChapter = chapters.find((chapter) => Number(chapter.number) === latestNumber) || chapters.at(-1);
  const volumes = getVolumes(state.series);
  state.volume = latestChapter?.volume ?? volumes.at(-1)?.[0] ?? null;
  state.selectedChapterId = latestChapter?.id ?? null;
}

function bindEvents() {
  els.volumeSelect.addEventListener('change', () => {
    state.volume = els.volumeSelect.value;
    state.search = '';
    state.selectedChapterId = null;
    els.chapterSearch.value = '';
    renderAll();
  });

  els.chapterSearch.addEventListener('input', () => {
    state.search = els.chapterSearch.value;
    state.selectedChapterId = null;
    renderChapterSelect();
    renderChapterGrid();
    renderStats();
  });

  els.chapterSelect.addEventListener('change', () => {
    state.selectedChapterId = els.chapterSelect.value;
  });

  els.form.addEventListener('submit', (event) => {
    event.preventDefault();
    const chapterId = els.chapterSelect.value;
    if (!chapterId) return;
    state.selectedChapterId = chapterId;
    window.location.href = chapterHref(state.series.id, chapterId);
  });
}

setupHomeVideo();
bindEvents();
renderFooter();

loadManifest()
  .then((manifest) => {
    state.manifest = manifest;
    selectDefaultState(manifest);
    renderAll();
  })
  .catch((error) => {
    els.chapterGrid.innerHTML = `
      <article class="empty-state">
        <h3>Errore caricamento</h3>
        <p>${error.message}</p>
      </article>
    `;
  });
