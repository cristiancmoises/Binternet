/* Optional, same-origin progressive enhancement. Manual pagination always works. */
(function () {
  'use strict';

  const DEFAULTS = {theme: 'black', view: 'masonry', quality: 'auto', scroll: 'manual'};
  const ALLOWED_PARAMS = new Set(['q', 'bookmark', ...Object.keys(DEFAULTS)]);
  const MAX_HTML_BYTES = 2 * 1024 * 1024;
  const MAX_BOOKMARK_BYTES = 4096;

  function validateNextUrl(value, contextValue) {
    const context = new URL(contextValue);
    const url = new URL(value, context);
    const expectedPath = new URL('search.php', context).pathname;
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== context.origin ||
        url.pathname !== expectedPath || url.username || url.password || url.hash) {
      throw new Error('Invalid next-page address.');
    }
    for (const key of url.searchParams.keys()) {
      if (!ALLOWED_PARAMS.has(key) || url.searchParams.getAll(key).length !== 1) {
        throw new Error('Invalid next-page settings.');
      }
    }
    if (url.searchParams.get('q') !== (context.searchParams.get('q') || '').trim()) {
      throw new Error('The next page belongs to another search.');
    }
    for (const [key, fallback] of Object.entries(DEFAULTS)) {
      if ((url.searchParams.get(key) || fallback) !== (context.searchParams.get(key) || fallback)) {
        throw new Error('The next page changed your settings.');
      }
    }
    const bookmark = url.searchParams.get('bookmark');
    if (!bookmark || new TextEncoder().encode(bookmark).length > MAX_BOOKMARK_BYTES || /[\u0000-\u001f\u007f]/.test(bookmark)) {
      throw new Error('Invalid next-page bookmark.');
    }
    url.searchParams.sort();
    return url.href;
  }

  function validateImageUrl(value, contextValue) {
    const context = new URL(contextValue);
    const url = new URL(value, context);
    if (url.origin !== context.origin || url.pathname !== new URL('image_proxy.php', context).pathname ||
        url.username || url.password || url.hash || [...url.searchParams.keys()].some(key => key !== 'url') ||
        url.searchParams.getAll('url').length !== 1) {
      throw new Error('Invalid image address.');
    }
    const image = new URL(url.searchParams.get('url'));
    if (image.protocol !== 'https:' || image.hostname !== 'i.pinimg.com' ||
        image.username || image.password || image.hash || (image.port && image.port !== '443')) {
      throw new Error('Invalid image source.');
    }
    return url.href;
  }

  function createPager(options) {
    const seenImages = new Set(options.initialKeys || []);
    const seenBookmarks = new Set();
    const firstBookmark = new URL(options.contextUrl).searchParams.get('bookmark');
    if (firstBookmark) seenBookmarks.add(firstBookmark);
    let nextUrl = options.initialUrl ? validateNextUrl(options.initialUrl, options.contextUrl) : null;
    let loading = false;
    let paused = false;
    let ended = !nextUrl;
    let error = '';
    let note = '';
    let request = null;
    let disposed = false;
    const state = () => ({nextUrl, loading, paused, ended, error, note, count: seenImages.size});
    const emit = () => { if (!disposed) options.onState(state()); };

    async function loadNext(retry = false) {
      if (disposed || loading || paused || ended || (error && !retry)) return false;
      error = '';
      const requested = nextUrl;
      const bookmark = new URL(requested).searchParams.get('bookmark');
      if (seenBookmarks.has(bookmark)) {
        ended = true;
        nextUrl = null;
        note = 'Pinterest repeated a page. Start a new search to explore more.';
        emit();
        return false;
      }
      request = new AbortController();
      const activeRequest = request;
      let timedOut = false;
      const timer = setTimeout(() => { timedOut = true; activeRequest.abort(); }, options.timeoutMs || 15000);
      loading = true;
      emit();
      try {
        const page = await options.load(requested, activeRequest.signal);
        if (disposed) return false;
        if (activeRequest.signal.aborted) throw new Error('Loading was interrupted.');
        let following = page.nextUrl ? validateNextUrl(page.nextUrl, options.contextUrl) : null;
        const nextBookmark = following && new URL(following).searchParams.get('bookmark');
        const repeats = nextBookmark && (nextBookmark === bookmark || seenBookmarks.has(nextBookmark));
        if (repeats) following = null;
        const unique = [];
        const pageKeys = new Set();
        for (const card of page.cards) {
          if (card.key && !seenImages.has(card.key) && !pageKeys.has(card.key)) {
            unique.push(card);
            pageKeys.add(card.key);
          }
        }
        if (unique.length) {
          options.append(unique);
          for (const key of pageKeys) seenImages.add(key);
        }
        seenBookmarks.add(bookmark);
        nextUrl = following;
        if (!following || unique.length === 0) {
          ended = true;
          note = repeats ? 'Pinterest repeated a page. Start a new search to explore more.' :
            unique.length === 0 && following ? 'No new images on that page. Continue with Next page.' :
              'You’ve reached the end of these results.';
        }
        return true;
      } catch (failure) {
        if (!disposed && !(activeRequest.signal.aborted && paused && !timedOut)) error = timedOut ? 'Loading took too long. Retry when you are ready, or use Next page.' :
          (failure.message || 'Could not load more images. Retry or use Next page.');
        return false;
      } finally {
        clearTimeout(timer);
        // Also release an unread error or oversized response body.
        activeRequest.abort();
        request = null;
        loading = false;
        emit();
      }
    }

    return {
      loadNext,
      state,
      togglePause() { paused = !paused; emit(); return paused; },
      suspend() { paused = true; if (request) request.abort(); emit(); },
      destroy() { disposed = true; if (request) request.abort(); },
    };
  }

  async function readBoundedHtml(response) {
    const declared = Number(response.headers.get('content-length'));
    if (Number.isFinite(declared) && declared > MAX_HTML_BYTES) throw new Error('The next page is too large. Use Next page.');
    if (!response.body || !response.body.getReader) throw new Error('This browser cannot load more automatically. Use Next page.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let bytes = 0;
    let html = '';
    try {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        bytes += part.value.byteLength;
        if (bytes > MAX_HTML_BYTES) throw new Error('The next page is too large. Use Next page.');
        html += decoder.decode(part.value, {stream: true});
      }
      return html + decoder.decode();
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  function parsePage(html, contextUrl) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const gallery = doc.getElementById('image-gallery');
    if (!gallery) throw new Error('The next page did not contain a gallery. Use Next page or retry.');
    const cards = [];
    for (const figure of gallery.querySelectorAll('.image-card')) {
      const link = figure.querySelector('.image-link');
      const img = link && link.querySelector('img');
      if (!link || !img) throw new Error('The next page contained an incomplete image.');
      const original = validateImageUrl(link.getAttribute('href'), contextUrl);
      const src = validateImageUrl(img.getAttribute('src'), contextUrl);
      const srcset = (img.getAttribute('srcset') || '').split(',').filter(Boolean).map(candidate => {
        const match = candidate.trim().match(/^(\S+)\s+([1-9]\d{0,4})w$/);
        if (!match) throw new Error('The next page contained invalid image sizes.');
        return validateImageUrl(match[1], contextUrl) + ' ' + match[2] + 'w';
      }).join(', ');
      const width = Number(img.getAttribute('width'));
      const height = Number(img.getAttribute('height'));
      const title = (figure.querySelector('.image-title') || img).textContent || img.getAttribute('alt') || 'Image';
      cards.push({key: original, original, src, srcset, title: title.slice(0, 2048),
        width: Number.isInteger(width) && width > 0 && width <= 30000 ? width : 0,
        height: Number.isInteger(height) && height > 0 && height <= 30000 ? height : 0});
    }
    const next = doc.getElementById('next-page');
    return {cards, nextUrl: next ? validateNextUrl(next.getAttribute('href'), contextUrl) : null};
  }

  function appendCards(gallery, cards, contextUrl) {
    const view = new URL(contextUrl).searchParams.get('view') || 'masonry';
    const safeView = ['masonry', 'grid', 'compact', 'justified', 'focus'].includes(view) ? view : 'masonry';
    const section = document.createElement('section');
    section.className = 'gallery-page gallery gallery-' + safeView;
    section.setAttribute('aria-label', 'More image search results');
    for (const card of cards) {
      const ratio = card.height ? card.width / card.height : 1;
      const figure = document.createElement('figure');
      figure.className = 'image-card image-' + (ratio > 1.35 ? 'wide' : ratio < 0.8 ? 'tall' : 'square');
      const link = document.createElement('a');
      link.className = 'image-link';
      link.href = card.original;
      link.setAttribute('aria-label', 'Open original image: ' + card.title);
      const img = document.createElement('img');
      img.src = card.src;
      img.alt = card.title;
      img.loading = 'lazy';
      img.decoding = 'async';
      if (card.width && card.height) { img.width = card.width; img.height = card.height; }
      if (card.srcset) {
        img.srcset = card.srcset;
        img.sizes = safeView === 'focus' ? '(max-width: 760px) 94vw, 920px' :
          safeView === 'compact' ? '(max-width: 600px) 30vw, (max-width: 1100px) 20vw, 190px' :
            safeView === 'justified' ? '(max-width: 600px) 90vw, (max-width: 1100px) 45vw, 400px' :
              '(max-width: 600px) 46vw, (max-width: 1000px) 30vw, (max-width: 1400px) 23vw, 270px';
      }
      const overlay = document.createElement('span');
      overlay.className = 'image-open';
      overlay.setAttribute('aria-hidden', 'true');
      overlay.textContent = 'View original ↗';
      link.append(img, overlay);
      const caption = document.createElement('figcaption');
      const title = document.createElement('span');
      title.className = 'image-title';
      title.textContent = card.title;
      caption.append(title);
      if (card.width && card.height) {
        const dimensions = document.createElement('span');
        dimensions.className = 'image-dimensions';
        dimensions.textContent = card.width + ' × ' + card.height;
        caption.append(dimensions);
      }
      figure.append(link, caption);
      section.append(figure);
    }
    gallery.append(section);
  }

  function bootstrap() {
    const gallery = document.getElementById('image-gallery');
    const next = document.getElementById('next-page');
    const sentinel = document.getElementById('scroll-sentinel');
    const status = document.getElementById('scroll-status');
    const toggle = document.getElementById('scroll-toggle');
    const retry = document.getElementById('scroll-retry');
    if (!gallery || gallery.dataset.scroll !== 'infinite' || !next || !sentinel || !status || !toggle || !retry ||
        !window.IntersectionObserver || !window.fetch || !window.AbortController) return;
    const contextUrl = window.location.href;
    let observer;
    let pager;
    try {
      pager = createPager({
        contextUrl,
        initialUrl: next.href,
        initialKeys: [...gallery.querySelectorAll('.image-link')].map(link => validateImageUrl(link.getAttribute('href'), contextUrl)),
        async load(url, signal) {
          const response = await fetch(url, {signal, credentials: 'same-origin', redirect: 'error',
            headers: {'Accept': 'text/html'}});
          if (!response.ok) {
            const upstream = response.headers.get('X-Binternet-Upstream-Status');
            const limited = response.status === 429 || upstream === '429';
            const refused = response.status === 403 || upstream === '403';
            throw new Error(limited ? 'Pinterest is limiting requests. Wait before retrying, or use Next page.' :
              refused ? 'Pinterest refused this request. Try again later, or use Next page.' :
                'Could not load more images (HTTP ' + response.status + '). Retry or use Next page.');
          }
          if (!(response.headers.get('content-type') || '').toLowerCase().startsWith('text/html')) {
            throw new Error('The next page had an unexpected format. Use Next page.');
          }
          return parsePage(await readBoundedHtml(response), contextUrl);
        },
        append(cards) { appendCards(gallery, cards, contextUrl); },
        onState(state) {
          gallery.setAttribute('aria-busy', String(state.loading));
          retry.hidden = !state.error;
          toggle.hidden = state.ended;
          toggle.textContent = state.paused ? 'Resume auto-loading' : 'Pause auto-loading';
          toggle.setAttribute('aria-pressed', String(state.paused));
          next.hidden = !state.nextUrl;
          if (state.nextUrl) next.href = state.nextUrl;
          status.textContent = state.error || state.note || (state.loading ? 'Loading more images…' :
            state.paused ? 'Auto-loading paused. ' + state.count + ' images loaded.' : state.count + ' images loaded. Scroll for more.');
          if (observer) {
            observer.disconnect();
            if (!state.loading && !state.paused && !state.ended && !state.error) observer.observe(sentinel);
          }
        },
      });
    } catch (_) {
      status.textContent = 'Automatic loading is unavailable. Continue with Next page.';
      return;
    }
    observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting) && !document.hidden) pager.loadNext();
    }, {rootMargin: '500px 0px'});
    toggle.hidden = false;
    toggle.addEventListener('click', () => pager.togglePause());
    retry.addEventListener('click', () => {
      if (pager.state().paused) pager.togglePause();
      pager.loadNext(true);
    });
    window.addEventListener('pagehide', () => { observer.disconnect(); pager.suspend(); });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && !pager.state().paused && !pager.state().ended && !pager.state().error) {
        observer.unobserve(sentinel);
        observer.observe(sentinel);
      }
    });
    observer.observe(sentinel);
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {validateNextUrl, validateImageUrl, createPager, readBoundedHtml, parsePage, appendCards};
  } else if (typeof window !== 'undefined') {
    bootstrap();
  }
}());
