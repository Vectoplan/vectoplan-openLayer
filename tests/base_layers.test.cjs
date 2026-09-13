const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../static/js/main.js'), 'utf8');
// Expose the private functions in the VM only; do not run the page bootstrap.
const testSource = source.replace('  if (document.readyState === "loading") {', `
  window.basemapTest = { createBaseLayers, syncInitialBanner, readMapDesignPreference };
  ensureMapStyleRenderer = window.loadRenderer;
  setBanner = window.notify;
  setToast = window.notify;
  if (document.readyState === "loading") {`);

class Source extends EventEmitter {
  constructor(options = {}) { super(); this.options = options; }
  setAttributions(value) { this.attributions = value; }
}

class Layer {
  constructor(options = {}) { this.options = options; this.visible = options.visible; }
  set(key, value) { this[key] = value; }
  setVisible(value) { this.visible = value; }
  getSource() { return this.options.source; }
}

class Group extends Layer {
  constructor(options) { super(options); this.layers = []; }
  getLayers() { return this.layers; }
}

function harness(options = {}) {
  const timers = new Map();
  let nextTimer = 0;
  const notifications = [];
  const styleCalls = [];
  let rendererLoads = 0;
  const vectorSource = new Source();
  const ol = {
    layer: { Tile: Layer, Group },
    source: { OSM: Source, XYZ: options.mapboxInitFails ? class { constructor() { throw Error('init'); } } : Source },
  };
  const window = {
    OPENLAYER_CONFIG: { token: 'pk.test-public-mapbox-token', ...options.config },
    location: { search: '' },
    localStorage: { getItem: () => options.savedPreference },
    notify: (...args) => notifications.push(args),
    loadRenderer: () => { rendererLoads++; return options.renderer ? options.renderer() : Promise.resolve(); },
    ol,
    olms: {
      apply(group, url) {
        styleCalls.push(url);
        group.getLayers().push(new Layer({ source: vectorSource }));
        return options.apply ? options.apply(group) : Promise.resolve(group);
      },
    },
  };
  vm.runInNewContext(readFileSync(path.join(__dirname, "../static/js/basemap.js"), "utf8") + testSource, {
    window, ol, URLSearchParams,
    document: { readyState: 'loading', addEventListener() {} },
    console: { info() {}, warn() {}, error() {} },
    setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  window.basemapTest.syncInitialBanner();
  const layers = window.basemapTest.createBaseLayers(options.designId);
  return {
    layers, notifications, styleCalls, vectorSource, timers,
    savedDesign: window.basemapTest.readMapDesignPreference(),
    get rendererLoads() { return rendererLoads; },
    timeout() {
      const entry = [...timers.entries()].find(([, timer]) => timer.delay === 12000);
      assert.ok(entry, 'a stalled provider has a timeout');
      timers.delete(entry[0]); entry[1].fn();
    },
  };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

function assertVisible(h, provider) {
  assert.equal(h.layers.provider, provider);
  for (const name of ['mapbox', 'openfreemap', 'osm']) {
    if (h.layers[name]) { assert.equal(h.layers[name].visible, name === provider, name); }
  }
  assert.deepEqual(h.notifications, [], 'provider changes never display messages');
}

test('configured Mapbox is disabled and OpenFreeMap starts immediately', async () => {
  const h = harness();
  await settle();
  assertVisible(h, 'openfreemap');
  assert.equal(h.layers.mapbox, null);
  assert.equal(h.rendererLoads, 1);
});

test('a completed neighbouring tile cannot disable the timeout of a stalled request', async () => {
  const h = harness();
  await settle();
  const source = h.vectorSource;
  source.emit('tileloadstart'); source.emit('tileloadstart'); source.emit('tileloadend');
  h.timeout(); await settle();
  assertVisible(h, 'osm');
});

for (const config of [
  { token: '' },
  { token: 'CHANGE_ME' },
  { styleTokenMismatch: true },
  { styleRequiresMapboxToken: false },
]) {
  test(`OpenFreeMap starts silently for ${JSON.stringify(config)}`, async () => {
    const h = harness({ config });
    await settle();
    assertVisible(h, 'openfreemap');
    assert.equal(h.layers.mapbox, null);
    assert.deepEqual(h.styleCalls, ['https://tiles.openfreemap.org/styles/positron']);
    assert.match(h.vectorSource.attributions, /OpenMapTiles/);
    assert.match(h.vectorSource.attributions, /openstreetmap.org\/copyright/);
  });
}

test('one OpenFreeMap renderer is created without any legacy Mapbox source', async () => {
  const h = harness();
  await settle();
  assertVisible(h, 'openfreemap');
  assert.equal(h.rendererLoads, 1);
  assert.equal(h.styleCalls.length, 1);
  assert.equal(h.layers.mapbox, null);
});

test('Mapbox construction failure uses OpenFreeMap', async () => {
  const h = harness({ mapboxInitFails: true });
  await settle();
  assertVisible(h, 'openfreemap');
});

test('a stalled OpenFreeMap request has a bounded fallback', async () => {
  const h = harness();
  h.timeout();
  await settle();
  assertVisible(h, 'osm');
});

for (const stage of ['renderer', 'apply']) {
  test(`${stage} failure falls back to OSM silently`, async () => {
    const h = harness({ config: { token: '' }, [stage]: () => Promise.reject(Error('offline')) });
    await settle();
    assertVisible(h, 'osm');
    assert.equal(h.timers.size, 0);
  });
}

test('OpenFreeMap tile errors fall back to OSM and never re-enable a failed provider', async () => {
  const h = harness();
  await settle();
  h.vectorSource.emit('tileloaderror');
  h.vectorSource.emit('tileloadend');
  h.vectorSource.emit('tileloaderror');
  assertVisible(h, 'osm');
  assert.equal(h.rendererLoads, 1);
});

test('late style completion after timeout cannot cover the OSM fallback', async () => {
  let complete;
  const h = harness({ config: { token: '' }, apply: () => new Promise(resolve => { complete = resolve; }) });
  await settle();
  h.timeout();
  complete();
  await settle();
  assertVisible(h, 'osm');
  assert.equal(h.layers.openfreemap.getLayers()[0].visible, false);
});

test('a hung renderer cannot delay the final fallback indefinitely', async () => {
  const h = harness({ config: { token: '' }, renderer: () => new Promise(() => {}) });
  await settle();
  h.timeout();
  assertVisible(h, 'osm');
  assert.equal(h.styleCalls.length, 0);
});

test('successful OpenFreeMap tiles cancel the timeout; later stalled tiles rearm it', async () => {
  const h = harness({ config: { token: '' } });
  await settle();
  h.vectorSource.emit('tileloadend');
  assert.equal(h.timers.size, 0);
  assertVisible(h, 'openfreemap');
  h.vectorSource.emit('tileloadstart');
  h.timeout();
  assertVisible(h, 'osm');
});

test('dark always uses OpenFreeMap even with a configured Mapbox token', async () => {
  const h = harness({ designId: 'dark' });
  await settle();
  assertVisible(h, 'openfreemap');
  assert.deepEqual(h.styleCalls, ['https://tiles.openfreemap.org/styles/dark']);
  h.vectorSource.emit('tileloaderror');
  assertVisible(h, 'osm');
  assert.equal(h.layers.designId, 'dark', 'provider fallback must not change the selected design');
});

test('dark without a token loads the dark fallback immediately', async () => {
  const h = harness({ designId: 'dark', config: { token: '' } });
  await settle();
  assertVisible(h, 'openfreemap');
  assert.equal(h.layers.mapbox, null);
  assert.deepEqual(h.styleCalls, ['https://tiles.openfreemap.org/styles/dark']);
});

for (const [savedPreference, expected] of [['bright', 'light'], ['liberty', 'light'], ['osm', 'light'], ['fiord', 'dark'], ['dark', 'dark']]) {
  test(`saved ${savedPreference} resolves to the single ${expected} entry`, () => {
    assert.equal(harness({ savedPreference }).savedDesign, expected);
  });
}

test('unknown saved styles use the primary design', () => {
  const h = harness({ designId: 'https://untrusted.example/style' });
  assertVisible(h, 'openfreemap');
});

test('switching designs while a style loads cancels its timer and ignores late completion', async () => {
  let complete;
  const h = harness({ designId: 'dark', config: { token: '' }, apply: () => new Promise(resolve => { complete = resolve; }) });
  await settle();
  h.layers.dispose();
  assert.equal(h.timers.size, 0);
  complete();
  await settle();
  assert.equal(h.layers.provider, null);
  assert.equal(h.layers.openfreemap.getLayers()[0].visible, false);
  assert.deepEqual(h.notifications, []);
});
