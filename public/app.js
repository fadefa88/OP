const els = {
  form: document.querySelector('#reader-picker-form'),
  seriesGrid: document.querySelector('#series-grid'),
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

function setupHomeVideo() {
  const video = document.querySelector('.home-backdrop-video');
  if (!video) return;

  const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  video.muted = true;
  video.defaultMuted = true;
  video.loop = true;
  video.autoplay = true;
  video.playsInline = true;
  video.controls = false;
  video.disablePictureInPicture = true;
  video.setAttribute('muted', '');
  video.setAttribute('autoplay', '');
  video.setAttribute('loop', '');
  video.setAttribute('playsinline', '');
  video.setAttribute('webkit-playsinline', '');
  video.removeAttribute('controls');
  video.removeAttribute('poster');

  const markPlaying = () => {
    document.body.classList.add('video-playing');
    document.body.classList.remove('video-autoplay-blocked');
  };

  const markBlocked = () => {
    document.body.classList.add('video-autoplay-blocked');
    if (!isIos) document.body.classList.add('video-playing');
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
    if (video.readyState === 0) video.load();
    const promise = video.play();
    if (promise?.then) promise.then(markPlaying).catch(markBlocked);
    else if (!video.paused) markPlaying();
    else markBlocked();
  };

  video.addEventListener('playing', markPlaying);
  video.addEventListener('play', markPlaying);
  video.addEventListener('canplay', tryPlay, { once: true });
  video.addEventListener('loadeddata', tryPlay, { once: true });
  video.addEventListener('ended', () => {
    video.currentTime = 0;
    tryPlay();
  });
  video.addEventListener('error', markBlocked);
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
  const response = await fetch('/content/manifest.json', { headers: { accept: 'application/json' }, cache: 'no-cache' });
  if (!response.ok) throw new Error('Archivio non disponibile');
  return response.json();
}

function naturalNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function getSeriesList() {
  return [...(state.manifest?.series || [])];
}

function getChapters(series = state.series) {
  return [...(series?.chapters || [])].sort((a, b) => naturalNumber(a.number) - naturalNumber(b.number));
}

function getVolumes(series = state.series) {
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

function option(label, value, selected = false) {
  const el = document.createElement('option');
  el.value = value;
  el.textContent = label;
  el.selected = selected;
  return el;
}

function latestChapterFor(series) {
  const chapters = getChapters(series);
  const latestNumber = Number(series?.latestChapter);
  return chapters.find((chapter) => Number(chapter.number) === latestNumber) || chapters.at(-1) || null;
}

function setSeries(seriesId, { preserveSearch = false } = {}) {
  const next = getSeriesList().find((item) => item.id === seriesId) || getSeriesList()[0];
  state.series = next || null;
  const latest = latestChapterFor(state.series);
  const volumes = getVolumes(state.series);
  state.volume = latest?.volume ?? volumes.at(-1)?.[0] ?? null;
  state.selectedChapterId = latest?.id ?? null;
  if (!preserveSearch) {
    state.search = '';
    if (els.chapterSearch) els.chapterSearch.value = '';
  }
}

function renderSeriesGrid() {
  if (!els.seriesGrid) return;
  els.seriesGrid.innerHTML = '';
  const fragment = document.createDocumentFragment();

  getSeriesList().forEach((series) => {
    const latest = latestChapterFor(series);
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `series-card ${series.id === state.series?.id ? 'is-active' : ''}`;
    card.innerHTML = `
      <span class="series-card-kicker">${series.id === 'opm' ? 'Nuova serie' : 'Serie principale'}</span>
      <strong>${series.title || series.id}</strong>
      <small>${latest ? `Ultimo capitolo ${latest.number}` : 'Pronta per importazione'}</small>
    `;
    card.addEventListener('click', () => {
      setSeries(series.id);
      renderAll();
      document.querySelector('#reader-picker')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    fragment.appendChild(card);
  });

  els.seriesGrid.appendChild(fragment);
}

function renderVolumeSelect() {
  const volumes = getVolumes(state.series);
  els.volumeSelect.innerHTML = '';

  volumes.forEach(([volume]) => {
    els.volumeSelect.appendChild(option(`Volume ${volume}`, String(volume), String(volume) === String(state.volume)));
  });

  if (!volumes.length) {
    els.volumeSelect.appendChild(option('Nessun volume', '', true));
    els.volumeSelect.disabled = true;
  } else {
    els.volumeSelect.disabled = false;
  }
}

function getVisibleChapters() {
  const query = state.search.trim().toLowerCase();

  if (query) {
    return getChapters(state.series).filter((chapter) => {
      const haystack = [chapter.title, chapter.number, chapter.volume, chapter.id, state.series?.title]
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

  if (!chapters.length) {
    els.chapterSelect.appendChild(option('Nessun capitolo', '', true));
    els.chapterSelect.disabled = true;
  } else {
    els.chapterSelect.disabled = false;
  }

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
        <h3>Nessun capitolo disponibile</h3>
        <p>${state.series?.id === 'opm' ? 'Lancia il workflow di importazione One Man Punch per popolare l’archivio.' : 'Prova a cambiare volume oppure svuotare la ricerca.'}</p>
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
        <strong>${state.series.title || 'Reader'} · ${chapter.title || `Capitolo ${chapter.number}`}</strong>
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
  els.volumeTitle.textContent = state.search ? 'Risultati ricerca' : `${state.series?.title || 'Archivio'} · Volume ${state.volume ?? '-'}`;
}

function renderQuickLinks() {
  const latest = latestChapterFor(state.series);
  if (!latest) {
    els.latestChapter.href = '#reader-picker';
    els.latestChapter.textContent = 'Archivio in preparazione';
    els.continueReading.href = '#reader-picker';
    els.continueReading.textContent = 'Archivio in preparazione';
    return;
  }

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
  renderSeriesGrid();
  renderVolumeSelect();
  renderChapterSelect();
  renderChapterGrid();
  renderStats();
  renderQuickLinks();
  renderFooter();
}

function selectDefaultState(manifest) {
  const seriesList = manifest.series || [];
  const preferred = seriesList.find((series) => series.id === 'op') || seriesList.find((series) => getChapters(series).length) || seriesList[0];
  state.series = preferred || null;
  setSeries(state.series?.id || preferred?.id || 'op');
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
    if (!chapterId || !state.series) return;
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
