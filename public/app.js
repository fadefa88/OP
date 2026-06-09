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
  search: ''
};

function setupHomeVideo() {
  const video = document.querySelector('.home-backdrop-video');
  if (!video) return;

  video.muted = true;
  video.defaultMuted = true;
  video.playsInline = true;
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
    document.body.classList.remove('video-playing');
  };

  const tryPlay = () => {
    video.muted = true;
    video.playsInline = true;
    const promise = video.play();
    if (promise?.then) {
      promise.then(markPlaying).catch(markBlocked);
    } else if (!video.paused) {
      markPlaying();
    }
  };

  video.addEventListener('playing', markPlaying);
  video.addEventListener('pause', () => {
    if (!document.hidden) markBlocked();
  });

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
  const response = await fetch('/api/manifest', { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error('Archivio non disponibile');
  const payload = await response.json();
  return payload.data;
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
  const previousValue = els.chapterSelect.value;
  els.chapterSelect.innerHTML = '';

  chapters.forEach((chapter) => {
    const label = `Cap. ${chapter.number ?? chapter.id}`;
    els.chapterSelect.appendChild(option(label, chapter.id, chapter.id === previousValue));
  });

  if (chapters.length && !chapters.some((chapter) => chapter.id === els.chapterSelect.value)) {
    els.chapterSelect.value = chapters[0].id;
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
  const volumes = getVolumes(state.series);
  const totalChapters = getChapters(state.series).length;
  const visibleCount = getVisibleChapters().length;
  els.libraryStats.textContent = `${volumes.length} volumi · ${totalChapters} capitoli · ${visibleCount} mostrati`;
  els.volumeTitle.textContent = state.search ? 'Risultati ricerca' : `Volume ${state.volume}`;
}

function renderQuickLinks() {
  const chapters = getChapters(state.series);
  const latest = chapters.at(-1);
  if (latest) {
    els.latestChapter.href = chapterHref(state.series.id, latest.id);
    els.latestChapter.textContent = `Ultimo capitolo: ${latest.number ?? latest.id}`;
  }

  const last = getLastReading();
  const lastSeries = state.manifest.series.find((series) => series.id === last?.seriesId);
  const lastChapter = lastSeries?.chapters?.find((chapter) => chapter.id === last?.chapterId);

  if (lastSeries && lastChapter) {
    els.continueReading.href = chapterHref(lastSeries.id, lastChapter.id, last.page || 1);
    els.continueReading.textContent = `Continua: cap. ${lastChapter.number ?? lastChapter.id}, pag. ${last.page || 1}`;
  } else if (latest) {
    els.continueReading.href = chapterHref(state.series.id, latest.id);
    els.continueReading.textContent = 'Apri ultimo capitolo';
  }
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
  const lastReading = getLastReading();
  const rememberedSeries = manifest.series.find((series) => series.id === lastReading?.seriesId);
  state.series = rememberedSeries || firstSeries;

  const volumes = getVolumes(state.series);
  const rememberedChapter = getChapters(state.series).find((chapter) => chapter.id === lastReading?.chapterId);
  state.volume = rememberedChapter?.volume ?? volumes.at(-1)?.[0] ?? null;
}

function bindEvents() {
  els.volumeSelect.addEventListener('change', () => {
    state.volume = els.volumeSelect.value;
    state.search = '';
    els.chapterSearch.value = '';
    renderAll();
  });

  els.chapterSearch.addEventListener('input', () => {
    state.search = els.chapterSearch.value;
    renderChapterSelect();
    renderChapterGrid();
    renderStats();
  });

  els.form.addEventListener('submit', (event) => {
    event.preventDefault();
    const chapterId = els.chapterSelect.value;
    if (!chapterId) return;
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
