const els = {
  form: document.querySelector('#reader-picker-form'),
  seriesSelect: document.querySelector('#series-select'),
  volumeSelect: document.querySelector('#volume-select'),
  chapterSelect: document.querySelector('#chapter-select'),
  chapterGrid: document.querySelector('#chapter-grid'),
  chapterSearch: document.querySelector('#chapter-search'),
  libraryStats: document.querySelector('#library-stats'),
  volumeTitle: document.querySelector('#volume-title'),
  latestChapter: document.querySelector('#latest-chapter'),
  continueReading: document.querySelector('#continue-reading')
};

const state = {
  manifest: null,
  series: null,
  volume: null,
  search: ''
};

async function loadManifest() {
  const response = await fetch('/api/manifest');
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

function renderSeriesSelect() {
  els.seriesSelect.innerHTML = '';
  state.manifest.series.forEach((series) => {
    els.seriesSelect.appendChild(option(series.title, series.id, series.id === state.series.id));
  });
}

function renderVolumeSelect() {
  const volumes = getVolumes(state.series);
  els.volumeSelect.innerHTML = '';

  volumes.forEach(([volume, chapters]) => {
    const label = `Volume ${volume} · ${chapters.length} capitoli`;
    els.volumeSelect.appendChild(option(label, String(volume), String(volume) === String(state.volume)));
  });

  if (!volumes.some(([volume]) => String(volume) === String(state.volume))) {
    state.volume = volumes.at(-1)?.[0] ?? null;
    if (state.volume !== null) els.volumeSelect.value = String(state.volume);
  }
}

function getVisibleChapters() {
  const query = state.search.trim().toLowerCase();
  let chapters = getChapters(state.series).filter((chapter) => String(chapter.volume ?? 'speciali') === String(state.volume));

  if (query) {
    chapters = getChapters(state.series).filter((chapter) => {
      const haystack = [chapter.title, chapter.number, chapter.volume, chapter.id]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  }

  return chapters;
}

function renderChapterSelect() {
  const chapters = getVisibleChapters();
  const previousValue = els.chapterSelect.value;
  els.chapterSelect.innerHTML = '';

  chapters.forEach((chapter) => {
    const pages = chapter.pages?.length || 0;
    const label = `Cap. ${chapter.number ?? chapter.id} · ${pages} pagine`;
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
        <small>Volume ${chapter.volume ?? 'speciali'} · ${chapter.pages?.length || 0} pagine</small>
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

function renderAll() {
  renderSeriesSelect();
  renderVolumeSelect();
  renderChapterSelect();
  renderChapterGrid();
  renderStats();
  renderQuickLinks();
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

els.seriesSelect.addEventListener('change', () => {
  state.series = state.manifest.series.find((series) => series.id === els.seriesSelect.value) || state.manifest.series[0];
  state.volume = getVolumes(state.series).at(-1)?.[0] ?? null;
  state.search = '';
  els.chapterSearch.value = '';
  renderAll();
});

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
