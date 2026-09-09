'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {validateNextUrl, validateImageUrl, createPager, readBoundedHtml, appendCards} = require('../static/infinite-scroll.js');

const context = 'https://binternet.example/search.php?q=architecture&theme=black&view=masonry&quality=auto&scroll=infinite';
const page = bookmark => context + '&bookmark=' + encodeURIComponent(bookmark);
const proxy = filename => 'https://binternet.example/image_proxy.php?url=' + encodeURIComponent('https://i.pinimg.com/originals/' + filename + '.jpg');
function makePager(overrides = {}) {
  const appended = [];
  const states = [];
  const pager = createPager({contextUrl: context, initialUrl: page('A'), initialKeys: ['first'],
    load: async () => ({cards: [{key: 'second'}], nextUrl: null}),
    append: cards => appended.push(...cards), onState: state => states.push(state), ...overrides});
  return {pager, appended, states};
}

 test('next-page URL keeps query and every preference, accepts opaque bookmarks', () => {
  const accepted = new URL(validateNextUrl(page('a&b+/_='), context));
  assert.equal(accepted.searchParams.get('bookmark'), 'a&b+/_=');
  for (const key of ['q', 'theme', 'view', 'quality', 'scroll']) {
    assert.equal(accepted.searchParams.get(key), new URL(context).searchParams.get(key));
  }
});

test('next-page validation blocks origin changes, credentials, other routes and settings', () => {
  for (const url of [
    page('A').replace('binternet.example', 'evil.example'),
    page('A').replace('https://', 'https://user@'),
    page('A').replace('/search.php', '/image_proxy.php'),
    page('A') + '#fragment', page('A') + '&q=architecture', page('A') + '&extra=yes',
    page('A').replace('q=architecture', 'q=birds'), page('A').replace('view=masonry', 'view=grid'),
    page('A').replace('quality=auto', 'quality=original'), page('A').replace('theme=black', 'theme=paper'),
    page('A').replace('scroll=infinite', 'scroll=manual'), page(''), page('A\rB'), page('a'.repeat(2049)),
  ]) assert.throws(() => validateNextUrl(url, context), Error, url);
});

test('image addresses allow only same-origin proxy and HTTPS Pinterest raster source host', () => {
  assert.equal(validateImageUrl(proxy('one'), context), proxy('one'));
  for (const url of [
    proxy('one').replace('binternet.example', 'evil.example'),
    proxy('one').replace('image_proxy.php', 'search.php'),
    'https://binternet.example/image_proxy.php?url=' + encodeURIComponent('https://evil.example/a.jpg'),
    'https://binternet.example/image_proxy.php?url=' + encodeURIComponent('http://i.pinimg.com/a.jpg'),
    'https://binternet.example/image_proxy.php?url=' + encodeURIComponent('https://user@i.pinimg.com/a.jpg'),
    proxy('one') + '&url=duplicate', proxy('one') + '&extra=1', 'javascript:alert(1)',
  ]) assert.throws(() => validateImageUrl(url, context), Error, url);
});

test('intersection bursts create one in-flight request and leave real next URL intact', async () => {
  let finish;
  let calls = 0;
  const {pager, appended} = makePager({load: () => { calls++; return new Promise(resolve => { finish = resolve; }); }});
  const first = pager.loadNext();
  assert.equal(pager.state().loading, true);
  assert.equal(await pager.loadNext(), false);
  assert.equal(await pager.loadNext(), false);
  assert.equal(new URL(pager.state().nextUrl).searchParams.get('bookmark'), 'A');
  finish({cards: [{key: 'second'}], nextUrl: page('B')});
  assert.equal(await first, true);
  assert.equal(calls, 1);
  assert.deepEqual(appended, [{key: 'second'}]);
  assert.equal(new URL(pager.state().nextUrl).searchParams.get('bookmark'), 'B');
});

test('duplicate images within and between pages are not appended twice', async () => {
  const {pager, appended} = makePager({load: async () => ({cards: [{key: 'first'}, {key: 'second'}, {key: 'second'}], nextUrl: page('B')})});
  await pager.loadNext();
  assert.deepEqual(appended, [{key: 'second'}]);
  assert.equal(pager.state().count, 2);
});

test('exhausted results stop requests and clear the next link', async () => {
  const {pager} = makePager();
  await pager.loadNext();
  assert.equal(pager.state().ended, true);
  assert.equal(pager.state().nextUrl, null);
  assert.equal(await pager.loadNext(), false);
  assert.match(pager.state().note, /end of these results/);
});

test('repeated bookmark is stopped even when URL query order changes', async () => {
  let calls = 0;
  const {pager} = makePager({load: async () => {
    calls++;
    const url = new URL(page('A'));
    url.searchParams.sort();
    return {cards: [{key: 'second'}], nextUrl: url.href};
  }});
  await pager.loadNext();
  assert.equal(pager.state().ended, true);
  assert.equal(pager.state().nextUrl, null);
  await pager.loadNext();
  assert.equal(calls, 1);
  assert.match(pager.state().note, /repeated/);
});

test('a cursor cycle across several pages is stopped', async () => {
  let count = 0;
  const {pager} = makePager({load: async () => ({cards: [{key: 'image' + ++count}], nextUrl: page(count === 1 ? 'B' : 'A')})});
  await pager.loadNext();
  await pager.loadNext();
  assert.equal(count, 2);
  assert.equal(pager.state().ended, true);
  assert.equal(pager.state().nextUrl, null);
});

test('a page with no new images stops automatic loading but preserves valid manual continuation', async () => {
  const {pager, appended} = makePager({load: async () => ({cards: [{key: 'first'}], nextUrl: page('B')})});
  await pager.loadNext();
  assert.equal(pager.state().ended, true);
  assert.equal(new URL(pager.state().nextUrl).searchParams.get('bookmark'), 'B');
  assert.deepEqual(appended, []);
  assert.match(pager.state().note, /No new images/);
});

test('network and provider errors stop automatic retries and preserve fallback URL', async () => {
  let calls = 0;
  const {pager} = makePager({load: async () => {
    if (++calls === 1) throw new Error('Pinterest is limiting requests.');
    return {cards: [{key: 'second'}], nextUrl: null};
  }});
  await pager.loadNext();
  assert.match(pager.state().error, /limiting/);
  assert.equal(new URL(pager.state().nextUrl).searchParams.get('bookmark'), 'A');
  await pager.loadNext();
  assert.equal(calls, 1);
  assert.equal(await pager.loadNext(true), true);
  assert.equal(calls, 2);
  assert.equal(pager.state().error, '');
});

test('invalid continuation rejects the response without appending image cards', async () => {
  const {pager, appended} = makePager({load: async () => ({cards: [{key: 'second'}], nextUrl: page('B').replace('q=architecture', 'q=birds')})});
  await pager.loadNext();
  assert.equal(pager.state().ended, false);
  assert.match(pager.state().error, /another search/);
  assert.deepEqual(appended, []);
});

test('pause blocks loads and resume permits continuation', async () => {
  const {pager} = makePager();
  assert.equal(pager.togglePause(), true);
  assert.equal(await pager.loadNext(), false);
  assert.equal(pager.togglePause(), false);
  assert.equal(await pager.loadNext(), true);
});

test('timeout aborts transport and requires explicit retry', async () => {
  let aborted = false;
  const {pager} = makePager({timeoutMs: 5, load: (_url, signal) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')); });
  })});
  await pager.loadNext();
  assert.equal(aborted, true);
  assert.equal(pager.state().loading, false);
  assert.match(pager.state().error, /too long/);
  assert.equal(await pager.loadNext(), false);
});

test('page suspension cancels outstanding request without losing manual continuation', async () => {
  const {pager} = makePager({load: (_url, signal) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')));
  })});
  const pending = pager.loadNext();
  pager.suspend();
  await pending;
  assert.equal(pager.state().paused, true);
  assert.equal(pager.state().error, '');
  assert.equal(new URL(pager.state().nextUrl).searchParams.get('bookmark'), 'A');
});

test('HTML reader enforces decoded byte limit even without content length', async () => {
  assert.equal(await readBoundedHtml(new Response('<p>ok</p>')), '<p>ok</p>');
  await assert.rejects(readBoundedHtml(new Response('a'.repeat(2 * 1024 * 1024 + 1))), /too large/);
  await assert.rejects(readBoundedHtml(new Response('small', {headers: {'Content-Length': '99999999'}})), /too large/);
});

test('appending constructs text and local image attributes, retaining independent page layout', () => {
  const oldDocument = global.document;
  function element(tag) {
    return {tag, children: [], attributes: {}, setAttribute(key, value) { this.attributes[key] = value; },
      append(...nodes) { this.children.push(...nodes); }};
  }
  global.document = {createElement: element};
  try {
    const gallery = element('div');
    const title = '<img src=x onerror=alert(1)>';
    appendCards(gallery, [{original: proxy('one'), src: proxy('one'), srcset: '', title, width: 736, height: 1000}], context);
    assert.equal(gallery.children.length, 1);
    const section = gallery.children[0];
    assert.equal(section.className, 'gallery-page gallery gallery-masonry');
    const figure = section.children[0];
    const link = figure.children[0];
    assert.equal(link.children[0].loading, 'lazy');
    assert.equal(link.children[0].src, proxy('one'));
    assert.equal(figure.children[1].children[0].textContent, title);
    assert.equal(link.children[0].alt, title);
    assert.equal(link.children[0].innerHTML, undefined);
    assert.equal(figure.children[1].children[0].children.length, 0);
  } finally { global.document = oldDocument; }
});
