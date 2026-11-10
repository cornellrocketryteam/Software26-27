import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const fixture = () => ({
  schemaVersion: 1,
  fillStationWebSocketUrl: null,
  grafanaUrl: null,
  fieldMode: true,
  map: { tileUrl: '/tiles/{z}/{x}/{y}.png', tilesConfigured: false },
});

test('runtime configuration module exists', async () => {
  const available = await import('../src/runtimeConfig.ts').then(() => true).catch(() => false);
  assert.equal(available, true, 'runtime station configuration is not implemented');
});

test('safe default has no inferred device endpoint or prepared tiles', async () => {
  const { parseStationConfig, DEFAULT_STATION_CONFIG } = await import('../src/runtimeConfig.ts');
  assert.deepEqual(parseStationConfig(fixture()), DEFAULT_STATION_CONFIG);
});

test('validated deployment settings preserve explicit local endpoints', async () => {
  const { parseStationConfig } = await import('../src/runtimeConfig.ts');
  const config = fixture();
  config.fillStationWebSocketUrl = 'ws://fillstation.test:9000';
  config.grafanaUrl = '/grafana/';
  config.map.tilesConfigured = true;
  assert.deepEqual(parseStationConfig(config), config);
});

test('invalid configuration and embedded credentials are rejected', async () => {
  const { parseStationConfig } = await import('../src/runtimeConfig.ts');
  const configs = [null, [], {}, { ...fixture(), schemaVersion: 2 },
    { ...fixture(), fieldMode: 'true' }, { ...fixture(), adminPassword: 'not-allowed' },
    { ...fixture(), fillStationWebSocketUrl: 'http://example.invalid' },
    { ...fixture(), fillStationWebSocketUrl: 'ws://user:password@example.invalid' },
    { ...fixture(), fillStationWebSocketUrl: 'ws://example.invalid/#fragment' },
    { ...fixture(), fillStationWebSocketUrl: 'ws://example.invalid/#' },
    { ...fixture(), grafanaUrl: 'javascript:alert(1)' },
    { ...fixture(), grafanaUrl: '//example.invalid/grafana/' },
    { ...fixture(), map: { tileUrl: '/tiles/{z}/{x}/{y}.png', tilesConfigured: 'yes' } },
    { ...fixture(), map: { tileUrl: 'https://tiles.example.invalid/{z}/{x}/{y}.png', tilesConfigured: true } },
  ];
  for (const config of configs) assert.throws(() => parseStationConfig(config));
});

test('remote tiles require an explicit non-field configuration', async () => {
  const { parseStationConfig } = await import('../src/runtimeConfig.ts');
  const config = fixture();
  config.fieldMode = false;
  config.map = { tileUrl: 'https://tiles.example.invalid/{z}/{x}/{y}.png', tilesConfigured: true };
  assert.deepEqual(parseStationConfig(config), config);
});

test('loader requests only same-origin config without caching', async () => {
  const { loadStationConfig } = await import('../src/runtimeConfig.ts');
  const requests = [];
  const result = await loadStationConfig({ fetcher: async (url, options) => {
    requests.push({ url, options });
    return Response.json(fixture());
  } });
  assert.deepEqual(result.config, fixture());
  assert.equal(result.error, null);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/station-config.json');
  assert.equal(requests[0].options.cache, 'no-store');
});

test('missing, invalid and hanging config loads fail closed', async () => {
  const { loadStationConfig, DEFAULT_STATION_CONFIG } = await import('../src/runtimeConfig.ts');
  for (const fetcher of [
    async () => new Response('missing', { status: 404 }),
    async () => new Response('<html>SPA fallback</html>'),
    async () => Response.json({ schemaVersion: 8 }),
    async () => new Promise(() => {}),
  ]) {
    const result = await loadStationConfig({ fetcher, timeoutMs: 20 });
    assert.deepEqual(result.config, DEFAULT_STATION_CONFIG);
    assert.equal(typeof result.error, 'string');
  }
});

test('legacy heater prototype does not embed a device credential', async () => {
  const source = await readFile(new URL('../src/components/HeaterPanelComponent.tsx', import.meta.url), 'utf8');
  assert.equal(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(source), false,
    'legacy heater prototype contains an embedded credential');
});
