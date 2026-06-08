const params = new URLSearchParams(window.location.search);
const seriesId = params.get('series');
const chapterId = params.get('chapter');
const pagesEl = document.querySelector('#reader-pages');
const chapterListEl = document.querySelector('#chapter-list');
const modeToggle = document.querySelector('#mode-toggle');
const fitToggle = document.querySelector('#fit-toggle');
let mode = localStorage.getItem('reader.mode') || 'vertical';
let fit = localStorage.getItem('reader.fit') || 'fit-width';

async function loadManifest() {
  const response = await fetch('/api/manifest');
  if (!response.ok) throw new Error('Manifest API error');
  const payload = await response.json();
  return payload.data;
}

function chapterHref(seriesId, chapterId) {
  return `/reader.html?series=${encodeURIComponent(seriesId)}&chapter=${encodeURIComponent(chapterId)}`;
}

function applyReaderClasses() {
  pagesEl.classList.toggle('vertical', mode === 'vertical');
  pagesEl.classList.toggle('horizontal', mode === 'horizontal');
  pagesEl.classList.toggle('fit-width', fit === 'fit-width');
  pagesEl.classList.toggle('fit-height', fit === 'fit-height');
  modeToggle.textContent = mode === 'vertical' ? 'Verticale' : 'Orizzontale';
  fitToggle.textContent = fit === 'fit-width' ? 'Fit width' : 'Fit height';
}

function setNavLink(el, series, chapter) {
  if (!chapter) {
    el.setAttribute('aria-disabled', 'true');
    el.href = '#';
    el.style.opacity = '0.45';
    return;
  }
  el.removeAttribute('aria-disabled');
  el.href = chapterHref(series.id, chapter.id);
  el.style.opacity = '1';
}

function renderReader(manifest) {
  const series = manifest.series.find((item) => item.id === seriesId) || manifest.series[0];
  const chapter = series.chapters.find((item) => item.id === chapterId) || series.chapters[0];
  const currentIndex = series.chapters.findIndex((item) => item.id === chapter.id);

  document.title = `${chapter.title} - ${series.title}`;
  document.querySelector('#reader-series').textContent = series.title;
  document.querySelector('#reader-chapter').textContent = chapter.title;

  chapterListEl.innerHTML = '';
  series.chapters.forEach((item) => {
    const link = document.createElement('a');
    link.href = chapterHref(series.id, item.id);
    link.className = item.id === chapter.id ? 'active' : '';
    link.textContent = item.title;
    chapterListEl.appendChild(link);
  });

  pagesEl.innerHTML = '';
  chapter.pages.forEach((page, index) => {
    const img = document.createElement('img');
    img.src = page.src;
    img.alt = `${chapter.title}, pagina ${index + 1}`;
    img.loading = index < 2 ? 'eager' : 'lazy';
    img.decoding = 'async';
    pagesEl.appendChild(img);
  });

  setNavLink(document.querySelector('#prev-chapter'), series, series.chapters[currentIndex - 1]);
  setNavLink(document.querySelector('#next-chapter'), series, series.chapters[currentIndex + 1]);
  applyReaderClasses();
}

modeToggle.addEventListener('click', () => {
  mode = mode === 'vertical' ? 'horizontal' : 'vertical';
  localStorage.setItem('reader.mode', mode);
  applyReaderClasses();
});

fitToggle.addEventListener('click', () => {
  fit = fit === 'fit-width' ? 'fit-height' : 'fit-width';
  localStorage.setItem('reader.fit', fit);
  applyReaderClasses();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowRight') document.querySelector('#next-chapter')?.click();
  if (event.key === 'ArrowLeft') document.querySelector('#prev-chapter')?.click();
});

loadManifest()
  .then(renderReader)
  .catch((error) => {
    pagesEl.innerHTML = `<p class="reader-placeholder">Errore: ${error.message}</p>`;
  });
