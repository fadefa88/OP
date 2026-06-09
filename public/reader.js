const params = new URLSearchParams(window.location.search);
const requestedSeriesId = params.get('series');
const requestedChapterId = params.get('chapter');
const requestedPage = Math.max(1, Number(params.get('page') || 1));

const els = {
  seriesTitle: document.querySelector('#reader-series'),
  chapterTitle: document.querySelector('#reader-chapter'),
  volumeSelect: document.querySelector('#reader-volume-select'),
  chapterSelect: document.querySelector('#reader-chapter-select'),
  pageSelect: document.querySelector('#reader-page-select'),
  image: document.querySelector('#reader-image'),
  loading: document.querySelector('#reader-loading'),
  singleView: document.querySelector('#single-page-view'),
  scrollReader: document.querySelector('#scroll-reader'),
  prevPage: document.querySelector('#prev-page'),
  nextPage: document.querySelector('#next-page'),
  prevChapter: document.querySelector('#prev-chapter'),
  nextChapter: document.querySelector('#next-chapter'),
  pageCounter: document.querySelector('#page-counter'),
  viewToggle: document.querySelector('#view-toggle'),
  fitToggle: document.querySelector('#fit-toggle'),
  fullscreenToggle: document.querySelector('#fullscreen-toggle'),
  fullscreenExit: document.querySelector('#fullscreen-exit'),
  fullscreenHint: document.querySelector('#fullscreen-hint')
};

const state = {
  manifest: null,
  series: null,
  chapter: null,
  chapterIndex: 0,
  pageIndex: requestedPage - 1,
  viewMode: localStorage.getItem('reader.viewMode') || 'paged',
  fitMode: localStorage.getItem('reader.fitMode') || 'width',
  uiHidden: false,
  immersiveFullscreen: false,
  restoreAfterFullscreen: null
};

async function loadManifest() {
  const response = await fetch('/api/manifest');
  if (!response.ok) throw new Error('Archivio non disponibile');
  const payload = await response.json();
  return payload.data;
}

function numberOr(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function getChapters(series) {
  return [...(series?.chapters || [])].sort((a, b) => numberOr(a.number) - numberOr(b.number));
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
  const next = new URLSearchParams({ series: seriesId, chapter: chapterId, page: String(page) });
  return `/reader.html?${next.toString()}`;
}

function updateUrl() {
  const url = chapterHref(state.series.id, state.chapter.id, state.pageIndex + 1);
  window.history.replaceState(null, '', url);
}

function rememberPosition() {
  localStorage.setItem('reader.last', JSON.stringify({
    seriesId: state.series.id,
    chapterId: state.chapter.id,
    page: state.pageIndex + 1,
    at: new Date().toISOString()
  }));
}

function setDisabledLink(el, disabled) {
  if (disabled) {
    el.href = '#';
    el.setAttribute('aria-disabled', 'true');
    el.classList.add('is-disabled');
  } else {
    el.removeAttribute('aria-disabled');
    el.classList.remove('is-disabled');
  }
}

function option(label, value, selected = false) {
  const el = document.createElement('option');
  el.value = value;
  el.textContent = label;
  el.selected = selected;
  return el;
}

function getPreviousChapter() {
  return getChapters(state.series)[state.chapterIndex - 1] || null;
}

function getNextChapter() {
  return getChapters(state.series)[state.chapterIndex + 1] || null;
}

function clampPageIndex(index) {
  const total = state.chapter?.pages?.length || 1;
  return Math.max(0, Math.min(index, total - 1));
}

function preloadAroundCurrent() {
  const pages = state.chapter.pages || [];
  [state.pageIndex - 1, state.pageIndex + 1].forEach((index) => {
    const src = pages[index]?.src;
    if (!src) return;
    const img = new Image();
    img.src = src;
  });
}

function renderSelectors() {
  const currentVolume = state.chapter.volume ?? 'speciali';

  els.volumeSelect.innerHTML = '';
  getVolumes(state.series).forEach(([volume, chapters]) => {
    els.volumeSelect.appendChild(option(`Volume ${volume} · ${chapters.length} cap.`, String(volume), String(volume) === String(currentVolume)));
  });

  els.chapterSelect.innerHTML = '';
  getChapters(state.series)
    .filter((chapter) => String(chapter.volume ?? 'speciali') === String(currentVolume))
    .forEach((chapter) => {
      const pages = chapter.pages?.length || 0;
      els.chapterSelect.appendChild(option(`Cap. ${chapter.number ?? chapter.id} · ${pages} pag.`, chapter.id, chapter.id === state.chapter.id));
    });

  els.pageSelect.innerHTML = '';
  const totalPages = state.chapter.pages?.length || 0;
  for (let index = 0; index < totalPages; index += 1) {
    els.pageSelect.appendChild(option(`Pagina ${index + 1}`, String(index + 1), index === state.pageIndex));
  }
}

function renderChapterNav() {
  const previous = getPreviousChapter();
  const next = getNextChapter();

  setDisabledLink(els.prevChapter, !previous);
  if (previous) {
    const lastPage = previous.pages?.length || 1;
    els.prevChapter.href = chapterHref(state.series.id, previous.id, lastPage);
  }

  setDisabledLink(els.nextChapter, !next);
  if (next) {
    els.nextChapter.href = chapterHref(state.series.id, next.id, 1);
  }
}

function renderPage() {
  const pages = state.chapter.pages || [];
  const page = pages[state.pageIndex];
  const totalPages = pages.length;

  document.title = `${state.chapter.title} · Pagina ${state.pageIndex + 1} - ${state.series.title}`;
  els.seriesTitle.textContent = state.series.title;
  els.chapterTitle.textContent = `${state.chapter.title} · pagina ${state.pageIndex + 1}/${totalPages}`;
  els.pageCounter.textContent = `Pagina ${state.pageIndex + 1} / ${totalPages}`;

  if (!page) {
    els.image.removeAttribute('src');
    els.image.alt = '';
    els.loading.textContent = 'Nessuna pagina disponibile.';
    els.loading.hidden = false;
    return;
  }

  els.loading.textContent = 'Caricamento…';
  els.loading.hidden = false;
  els.image.classList.remove('is-loaded');
  els.singleView.scrollTop = 0;
  els.image.alt = `${state.chapter.title}, pagina ${state.pageIndex + 1}`;
  els.image.src = page.src;
  els.pageSelect.value = String(state.pageIndex + 1);

  const hasPreviousPage = state.pageIndex > 0 || Boolean(getPreviousChapter());
  const hasNextPage = state.pageIndex < totalPages - 1 || Boolean(getNextChapter());
  els.prevPage.disabled = !hasPreviousPage;
  els.nextPage.disabled = !hasNextPage;

  updateUrl();
  rememberPosition();
  preloadAroundCurrent();
}

function renderScrollReader() {
  els.scrollReader.innerHTML = '';
  const fragment = document.createDocumentFragment();
  (state.chapter.pages || []).forEach((page, index) => {
    const img = document.createElement('img');
    img.src = page.src;
    img.alt = `${state.chapter.title}, pagina ${index + 1}`;
    img.loading = index < 2 ? 'eager' : 'lazy';
    img.decoding = 'async';
    fragment.appendChild(img);
  });
  els.scrollReader.appendChild(fragment);
}

function applyViewMode() {
  const paged = state.viewMode === 'paged';
  document.body.classList.toggle('scroll-mode', !paged);
  els.viewToggle.textContent = paged ? 'Pagina singola' : 'Scroll verticale';
  els.viewToggle.setAttribute('aria-pressed', String(!paged));
  localStorage.setItem('reader.viewMode', state.viewMode);
}

function applyFitMode() {
  const fitWidth = state.fitMode === 'width';
  document.body.classList.toggle('fit-width', fitWidth);
  document.body.classList.toggle('fit-page', !fitWidth);
  els.fitToggle.textContent = fitWidth ? 'Fit larghezza' : 'Pagina intera';
  els.fitToggle.setAttribute('aria-pressed', String(fitWidth));
  localStorage.setItem('reader.fitMode', state.fitMode);
}

let uiTimer = null;
let fullscreenHintTimer = null;

function isDesktopFullscreenLayout() {
  return window.matchMedia('(hover: hover) and (pointer: fine) and (min-width: 821px)').matches;
}


function setUiHidden(hidden) {
  state.uiHidden = hidden;
  document.body.classList.toggle('reader-ui-hidden', hidden);
}

function flashFullscreenHint() {
  if (!els.fullscreenHint) return;
  if (fullscreenHintTimer) window.clearTimeout(fullscreenHintTimer);
  els.fullscreenHint.hidden = false;
  requestAnimationFrame(() => els.fullscreenHint.classList.add('is-visible'));
  fullscreenHintTimer = window.setTimeout(() => {
    els.fullscreenHint.classList.remove('is-visible');
    window.setTimeout(() => {
      if (!els.fullscreenHint.classList.contains('is-visible')) els.fullscreenHint.hidden = true;
    }, 220);
  }, 1900);
}

function showReaderUi({ keep = false, force = false } = {}) {
  if (uiTimer) window.clearTimeout(uiTimer);

  if (state.immersiveFullscreen && !force) {
    setUiHidden(true);
    return;
  }

  setUiHidden(false);
  if (keep || state.viewMode !== 'paged') return;
  uiTimer = window.setTimeout(() => {
    const activeTag = document.activeElement?.tagName?.toLowerCase();
    if (['input', 'select', 'textarea', 'button'].includes(activeTag)) return;
    setUiHidden(true);
  }, 2600);
}

function applyFullscreenState(active) {
  const nextActive = Boolean(active);

  if (nextActive && !state.immersiveFullscreen) {
    state.restoreAfterFullscreen = {
      viewMode: state.viewMode,
      fitMode: state.fitMode
    };
    state.viewMode = 'paged';
    state.fitMode = isDesktopFullscreenLayout() ? 'page' : 'width';
    applyViewMode();
    applyFitMode();
  }

  if (!nextActive && state.immersiveFullscreen && state.restoreAfterFullscreen) {
    state.viewMode = state.restoreAfterFullscreen.viewMode;
    state.fitMode = state.restoreAfterFullscreen.fitMode;
    state.restoreAfterFullscreen = null;
    applyViewMode();
    applyFitMode();
  }

  state.immersiveFullscreen = nextActive;
  document.body.classList.toggle('reader-fullscreen', state.immersiveFullscreen);
  els.fullscreenToggle.textContent = state.immersiveFullscreen ? 'Esci' : 'Schermo intero';
  els.fullscreenToggle.setAttribute('aria-pressed', String(state.immersiveFullscreen));
  if (els.fullscreenExit) {
    els.fullscreenExit.hidden = !state.immersiveFullscreen;
    els.fullscreenExit.setAttribute('aria-hidden', String(!state.immersiveFullscreen));
  }

  if (state.immersiveFullscreen) {
    setUiHidden(true);
    flashFullscreenHint();
  } else {
    if (els.fullscreenHint) {
      els.fullscreenHint.classList.remove('is-visible');
      els.fullscreenHint.hidden = true;
    }
    showReaderUi({ keep: true, force: true });
  }
}

async function toggleFullscreen() {
  const target = document.documentElement;
  const nativeFullscreenActive = Boolean(document.fullscreenElement);

  if (state.immersiveFullscreen || nativeFullscreenActive) {
    if (nativeFullscreenActive && document.exitFullscreen) {
      try {
        await document.exitFullscreen();
      } catch (_) {
        // Some mobile browsers reject this if the gesture context has expired.
      }
    }
    applyFullscreenState(false);
    return;
  }

  applyFullscreenState(true);

  if (target.requestFullscreen) {
    try {
      await target.requestFullscreen({ navigationUI: 'hide' });
    } catch (_) {
      // iOS/Safari may not allow native fullscreen for normal pages.
      // The CSS fullscreen mode remains active as a fallback.
    }
  }
}

function renderAll() {
  state.pageIndex = clampPageIndex(state.pageIndex);
  renderSelectors();
  renderChapterNav();
  renderPage();
  renderScrollReader();
  applyViewMode();
  applyFitMode();
  showReaderUi();
}

function setChapter(chapterId, page = 1) {
  const chapters = getChapters(state.series);
  const index = chapters.findIndex((chapter) => chapter.id === chapterId);
  if (index === -1) return;
  state.chapter = chapters[index];
  state.chapterIndex = index;
  state.pageIndex = clampPageIndex(page - 1);
  renderAll();
}

function goToPage(index) {
  state.pageIndex = clampPageIndex(index);
  renderPage();
  showReaderUi();
}

function goNextPage() {
  const total = state.chapter.pages?.length || 0;
  if (state.pageIndex < total - 1) {
    goToPage(state.pageIndex + 1);
    return;
  }

  const next = getNextChapter();
  if (next) setChapter(next.id, 1);
}

function goPreviousPage() {
  if (state.pageIndex > 0) {
    goToPage(state.pageIndex - 1);
    return;
  }

  const previous = getPreviousChapter();
  if (previous) setChapter(previous.id, previous.pages?.length || 1);
}

function selectInitialState(manifest) {
  const firstSeries = manifest.series[0];
  state.series = manifest.series.find((series) => series.id === requestedSeriesId) || firstSeries;

  const chapters = getChapters(state.series);
  state.chapterIndex = Math.max(0, chapters.findIndex((chapter) => chapter.id === requestedChapterId));
  if (state.chapterIndex === -1) state.chapterIndex = 0;
  state.chapter = chapters[state.chapterIndex];
  state.pageIndex = clampPageIndex(requestedPage - 1);
}

els.image.addEventListener('load', () => {
  els.loading.hidden = true;
  els.image.classList.add('is-loaded');
  requestAnimationFrame(() => {
    els.singleView.scrollTop = 0;
  });
});

els.image.addEventListener('error', () => {
  els.loading.textContent = 'Immagine non caricata.';
  els.loading.hidden = false;
});

els.prevPage.addEventListener('click', () => {
  if (!state.immersiveFullscreen) showReaderUi({ keep: true });
  goPreviousPage();
});
els.nextPage.addEventListener('click', () => {
  if (!state.immersiveFullscreen) showReaderUi({ keep: true });
  goNextPage();
});

els.volumeSelect.addEventListener('change', () => {
  const chapter = getChapters(state.series).find((item) => String(item.volume ?? 'speciali') === els.volumeSelect.value);
  if (chapter) setChapter(chapter.id, 1);
});

els.chapterSelect.addEventListener('change', () => {
  setChapter(els.chapterSelect.value, 1);
});

els.pageSelect.addEventListener('change', () => {
  goToPage(Number(els.pageSelect.value) - 1);
});

els.viewToggle.addEventListener('click', () => {
  state.viewMode = state.viewMode === 'paged' ? 'scroll' : 'paged';
  applyViewMode();
  showReaderUi({ keep: true });
});

els.fitToggle.addEventListener('click', () => {
  state.fitMode = state.fitMode === 'width' ? 'page' : 'width';
  applyFitMode();
  els.singleView.scrollTop = 0;
  showReaderUi({ keep: true });
});

els.fullscreenToggle.addEventListener('click', () => {
  toggleFullscreen();
});

els.fullscreenExit?.addEventListener('click', (event) => {
  event.preventDefault();
  event.stopPropagation();
  toggleFullscreen();
});

document.addEventListener('fullscreenchange', () => {
  applyFullscreenState(Boolean(document.fullscreenElement));
});

document.addEventListener('keydown', (event) => {
  const activeTag = document.activeElement?.tagName?.toLowerCase();
  if (['input', 'select', 'textarea'].includes(activeTag)) return;

  if (event.key === 'ArrowRight') {
    event.preventDefault();
    goNextPage();
  }

  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    goPreviousPage();
  }

  if (event.key === 'Escape' && state.immersiveFullscreen) {
    event.preventDefault();
    toggleFullscreen();
  }

  if ((event.key === ' ' || event.key.toLowerCase() === 'h') && !state.immersiveFullscreen) {
    event.preventDefault();
    setUiHidden(!state.uiHidden);
  }

  if (event.key.toLowerCase() === 'f') {
    event.preventDefault();
    toggleFullscreen();
  }
});

let touchStartX = 0;
let touchStartY = 0;
let touchMoved = false;
let longPressTimer = null;
let longPressTriggered = false;
let ignoreClickUntil = 0;

const LONG_PRESS_TO_EXIT_MS = 720;

function clearLongPressTimer() {
  if (longPressTimer) {
    window.clearTimeout(longPressTimer);
    longPressTimer = null;
  }
}

function isCenterGesture(clientX) {
  const rect = els.singleView.getBoundingClientRect();
  const x = clientX - rect.left;
  return x >= rect.width * 0.34 && x <= rect.width * 0.66;
}

els.singleView.addEventListener('touchstart', (event) => {
  const touch = event.changedTouches[0];
  touchStartX = touch.clientX;
  touchStartY = touch.clientY;
  touchMoved = false;
  longPressTriggered = false;

  clearLongPressTimer();

  if (state.immersiveFullscreen && isCenterGesture(touch.clientX)) {
    longPressTimer = window.setTimeout(() => {
      longPressTriggered = true;
      ignoreClickUntil = Date.now() + 700;
      toggleFullscreen();
    }, LONG_PRESS_TO_EXIT_MS);
    return;
  }

  if (!state.immersiveFullscreen) showReaderUi();
}, { passive: true });

els.singleView.addEventListener('touchmove', (event) => {
  const touch = event.changedTouches[0];
  const movedX = Math.abs(touch.clientX - touchStartX);
  const movedY = Math.abs(touch.clientY - touchStartY);

  if (movedX > 8 || movedY > 8) touchMoved = true;
  if (movedX > 10 || movedY > 10) clearLongPressTimer();
}, { passive: true });

els.singleView.addEventListener('touchend', (event) => {
  clearLongPressTimer();
  if (longPressTriggered) return;

  const touch = event.changedTouches[0];
  const diffX = touch.clientX - touchStartX;
  const diffY = touch.clientY - touchStartY;

  if (Math.abs(diffX) >= 45 && Math.abs(diffX) > Math.abs(diffY)) {
    if (diffX < 0) goNextPage();
    else goPreviousPage();
  }
}, { passive: true });

els.singleView.addEventListener('touchcancel', () => {
  clearLongPressTimer();
}, { passive: true });

els.singleView.addEventListener('dblclick', (event) => {
  if (!state.immersiveFullscreen) return;
  const activeTag = event.target?.tagName?.toLowerCase();
  if (['select', 'button', 'a'].includes(activeTag)) return;
  if (!isCenterGesture(event.clientX)) return;

  event.preventDefault();
  ignoreClickUntil = Date.now() + 500;
  toggleFullscreen();
});

els.singleView.addEventListener('click', (event) => {
  if (touchMoved || Date.now() < ignoreClickUntil) return;
  const activeTag = event.target?.tagName?.toLowerCase();
  if (['select', 'button', 'a'].includes(activeTag)) return;

  const rect = els.singleView.getBoundingClientRect();
  const x = event.clientX - rect.left;

  if (x < rect.width * 0.28) {
    goPreviousPage();
    return;
  }

  if (x > rect.width * 0.72) {
    goNextPage();
    return;
  }

  if (state.immersiveFullscreen) {
    flashFullscreenHint();
    return;
  }

  setUiHidden(!state.uiHidden);
});

['mousemove', 'pointermove', 'focusin'].forEach((eventName) => {
  document.addEventListener(eventName, () => {
    if (state.immersiveFullscreen && eventName !== 'focusin') return;
    showReaderUi();
  }, { passive: true });
});

loadManifest()
  .then((manifest) => {
    state.manifest = manifest;
    selectInitialState(manifest);
    renderAll();
  })
  .catch((error) => {
    els.loading.textContent = `Errore: ${error.message}`;
    els.loading.hidden = false;
  });
