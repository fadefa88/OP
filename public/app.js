async function loadManifest() {
  const response = await fetch('/api/manifest');
  if (!response.ok) throw new Error('Manifest API error');
  const payload = await response.json();
  return payload.data;
}

function chapterHref(seriesId, chapterId) {
  return `/reader.html?series=${encodeURIComponent(seriesId)}&chapter=${encodeURIComponent(chapterId)}`;
}

function renderSeries(manifest) {
  const grid = document.querySelector('#series-grid');
  grid.innerHTML = '';

  manifest.series.forEach((series) => {
    const card = document.createElement('article');
    card.className = 'series-card';

    const cover = document.createElement('div');
    cover.className = 'series-cover';
    if (series.cover) {
      const img = document.createElement('img');
      img.src = series.cover;
      img.alt = `Cover ${series.title}`;
      cover.appendChild(img);
    } else {
      cover.textContent = series.title;
    }

    const content = document.createElement('div');
    content.className = 'series-content';
    content.innerHTML = `
      <h3>${series.title}</h3>
      <p>${series.description || ''}</p>
    `;

    series.chapters.forEach((chapter) => {
      const link = document.createElement('a');
      link.className = 'chapter-link';
      link.href = chapterHref(series.id, chapter.id);
      link.innerHTML = `<span>${chapter.title}</span><span>${chapter.pages.length} pagine</span>`;
      content.appendChild(link);
    });

    card.append(cover, content);
    grid.appendChild(card);
  });
}

loadManifest()
  .then(renderSeries)
  .catch((error) => {
    document.querySelector('#series-grid').innerHTML = `
      <div class="series-card">
        <div class="series-content">
          <h3>Errore caricamento</h3>
          <p>${error.message}</p>
        </div>
      </div>
    `;
  });
