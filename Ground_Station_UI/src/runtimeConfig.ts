export type StationConfig = Readonly<{
  schemaVersion: 1;
  fillStationWebSocketUrl: string | null;
  grafanaUrl: string | null;
  fieldMode: boolean;
  map: Readonly<{ tileUrl: string; tilesConfigured: boolean }>;
}>;

export const DEFAULT_STATION_CONFIG: StationConfig = Object.freeze({
  schemaVersion: 1,
  fillStationWebSocketUrl: null,
  grafanaUrl: null,
  fieldMode: true,
  map: Object.freeze({ tileUrl: '/tiles/{z}/{x}/{y}.png', tilesConfigured: false }),
});

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Station settings must be a JSON object.');
  }
  return value as Record<string, unknown>;
}

function keys(value: Record<string, unknown>, allowed: string[]) {
  if (Object.keys(value).some(key => !allowed.includes(key))) {
    throw new Error('Station settings contain unsupported fields.');
  }
}

function unsafeUrlChars(value: string) {
  return [...value].some(char => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127
    || char === '\\' || /\s/.test(char));
}

function localPath(value: string) {
  return value.startsWith('/') && !value.startsWith('//') && !unsafeUrlChars(value)
    && !value.split(/[/?#]/).some(part => part === '..' || part === '.');
}

function url(value: unknown, protocols: string[], relative = false): string {
  if (typeof value !== 'string' || !value || value.length > 2048 || unsafeUrlChars(value)) {
    throw new Error('A station endpoint has an invalid address.');
  }
  if (relative && localPath(value)) return value;
  let parsed: URL;
  try { parsed = new URL(value); }
  catch { throw new Error('A station endpoint has an invalid address.'); }
  if (!protocols.includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error('Station endpoints require supported protocols without embedded credentials.');
  }
  if (protocols.includes('ws:') && value.includes('#')) {
    throw new Error('WebSocket addresses must not contain fragments.');
  }
  return value;
}

export function parseStationConfig(value: unknown): StationConfig {
  const config = object(value);
  keys(config, ['schemaVersion', 'fillStationWebSocketUrl', 'grafanaUrl', 'fieldMode', 'map']);
  if (config.schemaVersion !== 1 || typeof config.fieldMode !== 'boolean') {
    throw new Error('Station settings version or field mode is invalid.');
  }
  const map = object(config.map);
  keys(map, ['tileUrl', 'tilesConfigured']);
  if (typeof map.tilesConfigured !== 'boolean') throw new Error('Map settings are invalid.');
  const tileUrl = url(map.tileUrl, ['http:', 'https:'], true);
  if (!['{z}', '{x}', '{y}'].every(token => tileUrl.includes(token))
      || (config.fieldMode && !localPath(tileUrl))) {
    throw new Error('Field maps require a local XYZ tile address.');
  }
  return Object.freeze({
    schemaVersion: 1,
    fillStationWebSocketUrl: config.fillStationWebSocketUrl === null ? null
      : url(config.fillStationWebSocketUrl, ['ws:', 'wss:']),
    grafanaUrl: config.grafanaUrl === null ? null : url(config.grafanaUrl, ['http:', 'https:'], true),
    fieldMode: config.fieldMode,
    map: Object.freeze({ tileUrl, tilesConfigured: map.tilesConfigured }),
  });
}

export async function loadStationConfig({ fetcher = fetch, timeoutMs = 3000 }: {
  fetcher?: typeof fetch; timeoutMs?: number;
} = {}): Promise<{ config: StationConfig; error: string | null }> {
  const abort = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const read = async () => {
      const response = await fetcher('/station-config.json', { cache: 'no-store', signal: abort.signal });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Station settings are unavailable.');
      }
      const text = await response.text();
      if (text.length > 65536) throw new Error('Station settings are too large.');
      return parseStationConfig(JSON.parse(text));
    };
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => { abort.abort(); reject(new Error('Station settings timed out.')); }, timeoutMs);
    });
    return { config: await Promise.race([read(), deadline]), error: null };
  } catch {
    return { config: DEFAULT_STATION_CONFIG, error: 'Station settings unavailable. Device connections are disabled.' };
  } finally {
    clearTimeout(timer);
    abort.abort();
  }
}
