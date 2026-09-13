// Run against tests/browser_preview.py. Requires Playwright and a local browser.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const baseUrl = process.env.MAP_TEST_URL || 'http://127.0.0.1:5191/';
const output = process.env.MAP_TEST_OUTPUT || path.join(__dirname, '../tmp/map-controls');

async function render(page) {
  await page.evaluate(() => new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(Error('render timed out')), 25000);
    vectoMap.once('rendercomplete', () => { clearTimeout(timeout); resolve(); });
    vectoMap.render();
  }));
}

async function assertBounds(page, label) {
  const result = await page.evaluate(() => {
    const view = vectoMap.getView();
    const extent = view.calculateExtent(vectoMap.getSize());
    const allowed = view.get('extent');
    return { extent, allowed, zoom: view.getZoom() };
  });
  assert.ok(result.extent.every(Number.isFinite), label + ': finite extent');
  const [a, b, c, d] = result.allowed;
  const [x, y, z, w] = result.extent;
  assert.ok(x >= a - 1e-6 && y >= b - 1e-6 && z <= c + 1e-6 && w <= d + 1e-6,
    label + ': viewport escaped ' + JSON.stringify(result));
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.route('**/static/js/main.js*', async route => {
      const response = await route.fetch();
      const source = (await response.text()).replace('  if (document.readyState === "loading") {', `
        window.__mapTest = { state, cfg, syncParcelSelection, updateProjectLocation, createDatasetLayer, clearDatasetLayer, getCurrentViewportContext };
        if (document.readyState === "loading") {`);
      await route.fulfill({ response, body: source });
    });
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.goto(baseUrl + '?initial_panel=none&zoom=0');
    await page.waitForFunction(() => window.__mapTest?.state.baseLayers.openfreemap?.getLayers().getArray().some(layer => layer.getVisible()));
    await render(page);
    await assertBounds(page, 'initial URL zoom=0');
    assert.equal(await page.locator('#toolbar-parcels-toggle, #parcel-selection-panel, [data-parcel-clear]').count(), 0);
    await page.getByRole('button', { name: 'Kartendesign auswählen' }).click();
    const options = page.locator('[data-map-design]');
    assert.equal(await options.count(), 2);
    assert.deepEqual(await options.evaluateAll(buttons => buttons.map(button => button.dataset.mapDesign)), ['light', 'dark']);
    assert.ok((await options.allTextContents()).every(text => text.trim() === ''));
    await page.waitForFunction(() => [...document.querySelectorAll('[data-map-design] img')].every(img => img.complete && img.naturalWidth === 360));
    await page.screenshot({ path: path.join(output, 'design-menu.png') });

    for (const design of ['dark', 'light']) {
      await page.locator('[data-map-design="' + design + '"]').click();
      await page.waitForFunction(design => {
        const base = __mapTest.state.baseLayers;
        return base.designId === design && (base.provider === 'osm'
          || base.openfreemap.getLayers().getArray().some(layer => layer.getVisible()));
      }, design);
      await render(page);
      assert.equal(await page.locator('[data-map-design="' + design + '"]').getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('.ol-attribution a[href="https://www.openmaptiles.org/"]').count(), 1);
      assert.equal(await page.locator('.ol-attribution a[href="https://www.openstreetmap.org/copyright"]').count(), 1);
      await assertBounds(page, 'design ' + design);
    }
    console.log('PASS exactly two designs, image-only options, single shared attribution and bounds');

    await page.locator('[data-map-design="dark"]').click();
    await page.reload();
    await page.waitForFunction(() => window.__mapTest?.state.baseLayers.designId === 'dark');
    await page.getByRole('button', { name: 'Kartendesign auswählen' }).click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#map-design-panel').isVisible(), false);
    await page.getByRole('button', { name: 'Kartendesign auswählen' }).click();
    await page.locator('#map').click({ position: { x: 50, y: 500 } });
    assert.equal(await page.locator('#map-design-panel').isVisible(), false);
    console.log('PASS saved preference, Escape and outside click');

    for (const [label, fn] of [
      ['setZoom', () => vectoMap.getView().setZoom(-10)],
      ['setCenter', () => vectoMap.getView().setCenter([1e7, 1e7])],
      ['fit world', () => vectoMap.getView().fit([-2e7, -2e7, 2e7, 2e7])],
      ['rotation', () => vectoMap.getView().setRotation(Math.PI / 4)],
      ['gesture overshoot', () => { const view = vectoMap.getView(); view.beginInteraction(); view.adjustZoom(-100); view.adjustCenter([1e8, -1e8]); }],
    ]) {
      await page.evaluate(fn);
      await assertBounds(page, label);
    }
    await page.evaluate(() => vectoMap.getView().endInteraction(0));
    await page.evaluate(() => new Promise(resolve => vectoMap.getView().animate({ center: [-1e7, -1e7], zoom: 0, duration: 200 }, resolve)));
    await assertBounds(page, 'animation');
    await page.setViewportSize({ width: 2560, height: 900 });
    await page.evaluate(() => vectoMap.updateSize());
    await assertBounds(page, 'wide viewport');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => vectoMap.updateSize());
    await assertBounds(page, 'mobile viewport');
    await page.getByRole('button', { name: 'Kartendesign auswählen' }).click();
    await page.screenshot({ path: path.join(output, 'design-menu-mobile.png') });
    await page.keyboard.press('Escape');
    await page.mouse.move(180, 500);
    await page.mouse.wheel(0, 10000);
    await page.waitForTimeout(350);
    await assertBounds(page, 'wheel zoom');
    await page.evaluate(() => __mapTest.updateProjectLocation([13.42, 52.53], { notifyParent: false, reloadDataset: false, autoSelect: false }));
    await assertBounds(page, 'changed project coordinate');
    await page.evaluate(() => vectoMap.getView().setCenter(ol.proj.fromLonLat([13.405, 52.52])));
    await assertBounds(page, 'old project area cannot be restored by panning');
    console.log('PASS URL, programmatic and gesture navigation, rotation, resize, coordinate changes');

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => {
      const { state, cfg, syncParcelSelection, createDatasetLayer } = __mapTest;
      state.view.setRotation(0);
      state.view.setCenter(ol.proj.fromLonLat([cfg.lon, cfg.lat]));
      state.view.setZoom(18);
      const ring = [[cfg.lon - .0005, cfg.lat - .0005], [cfg.lon + .0005, cfg.lat - .0005], [cfg.lon + .0005, cfg.lat + .0005], [cfg.lon - .0005, cfg.lat + .0005], [cfg.lon - .0005, cfg.lat - .0005]];
      const geometry = { type: 'Polygon', coordinates: [ring] };
      const dataset = { id: 'flurstuecke', title: 'Flurstücke', geometry_type: 'Polygon' };
      const feature = new ol.format.GeoJSON().readFeature({ type: 'Feature', id: 'fixture', geometry, properties: {} }, { featureProjection: 'EPSG:3857' });
      const result = createDatasetLayer(dataset, [feature]);
      state.activeDataset = dataset;
      state.datasetSource = result.source;
      state.datasetLayer = result.layer;
      state.datasets.lastViewportKey = __mapTest.getCurrentViewportContext().key;
      state.map.addLayer(result.layer);
      syncParcelSelection({ revision: 10, parcels: [{ parcelId: 'flurstuecke:fixture', datasetId: 'flurstuecke', geometry }] });
    });
    assert.equal(await page.evaluate(() => __mapTest.state.parcelSelection.source.getFeatures().length), 1);
    await render(page);
    const pixel = await page.evaluate(() => vectoMap.getPixelFromCoordinate(vectoMap.getView().getCenter()));
    await page.locator('#map').click({ position: { x: pixel[0] + 25, y: pixel[1] + 25 } });
    await page.waitForFunction(() => __mapTest.state.parcelSelection.source.getFeatures().length === 0, null, { timeout: 3000 }).catch(async error => {
      console.log(await page.evaluate(() => ({
        keys: Object.keys(__mapTest.state.parcelSelection.byId),
        features: __mapTest.state.datasetSource?.getFeatures().map(f => ({ id: f.getId(), extent: f.getGeometry().getExtent() })),
        readonly: __mapTest.cfg.parcelSelectionReadonly,
        center: vectoMap.getView().getCenter(),
        resolution: vectoMap.getView().getResolution(),
      })));
      throw error;
    });
    await page.locator('#map').click({ position: { x: pixel[0] + 25, y: pixel[1] + 25 } });
    await page.waitForFunction(() => __mapTest.state.parcelSelection.source.getFeatures().length === 1);
    await page.evaluate(() => __mapTest.clearDatasetLayer());
    assert.equal(await page.evaluate(() => __mapTest.state.parcelSelection.source.getFeatures().length), 1);
    await page.evaluate(() => window.postMessage({ type: 'vectoplan-app:parcel-selection-sync', detail: { revision: 99, parcels: [] } }, '*'));
    await page.waitForFunction(() => __mapTest.state.parcelSelection.source.getFeatures().length === 0);
    await page.evaluate(() => window.postMessage({ type: 'vectoplan-app:parcel-selection-sync', detail: { revision: 10, parcels: [{ parcelId: 'stale', geometry: { type: 'Polygon', coordinates: [] } }] } }, '*'));
    await page.waitForTimeout(50);
    assert.equal(await page.evaluate(() => __mapTest.state.parcelSelection.source.getFeatures().length), 0);
    console.log('PASS click selection, independent overlay, editor sync, clear and stale revision protection');
    assert.deepEqual(pageErrors, []);
    assert.equal(await page.locator('#map-status').isVisible(), false);
    assert.equal(await page.locator('#map-status-banner').isVisible(), false);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
