export type NetworkPort = {
  port: number; connectedDevice: string | null; poeCapable: boolean;
  connectivityCritical: boolean; powerControlEnabled: boolean;
};
export type NetworkDevice = {
  id: string; kind: 'shelly' | 'omada-switch' | 'omada-bridge'; model: string;
  address: string | null; connectedLoad?: string | null;
  state: 'not_configured' | 'inspection_pending' | 'available' | 'unavailable' | 'unknown';
  output: boolean | null; metrics: Record<string, number>; stale: boolean;
  lastSuccessUnixMs: number | null; canSetOutput: boolean; ports?: NetworkPort[];
};
export type NetworkSnapshot = {
  schemaVersion: 1; devices: NetworkDevice[]; powerWritesConfigured: boolean;
  operatorAuthorizationRequired: boolean;
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid network response');
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Invalid network text');
  return value;
}
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
function bool(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('Invalid network flag');
  return value;
}
export function parseNetworkSnapshot(value: unknown): NetworkSnapshot {
  const raw = object(value);
  if (raw.schemaVersion !== 1 || !Array.isArray(raw.devices)) throw new Error('Unsupported network response');
  const ids = new Set<string>();
  const devices = raw.devices.map((value): NetworkDevice => {
    const d = object(value); const id = text(d.id);
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(id) || ids.has(id)) throw new Error('Invalid network device identity');
    ids.add(id);
    if (!['shelly', 'omada-switch', 'omada-bridge'].includes(text(d.kind))) throw new Error('Unsupported device type');
    if (!['not_configured', 'inspection_pending', 'available', 'unavailable', 'unknown'].includes(text(d.state))) throw new Error('Invalid device state');
    const metrics: Record<string, number> = {};
    for (const [key, value] of Object.entries(object(d.metrics))) {
      if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Invalid metric');
      metrics[key] = value;
    }
    if (d.lastSuccessUnixMs !== null && (typeof d.lastSuccessUnixMs !== 'number' || !Number.isSafeInteger(d.lastSuccessUnixMs) || d.lastSuccessUnixMs < 0 || d.lastSuccessUnixMs > 8.64e15)) throw new Error('Invalid observation time');
    let ports: NetworkPort[] | undefined;
    if (d.ports !== undefined) {
      if (!Array.isArray(d.ports)) throw new Error('Invalid port list');
      const numbers = new Set<number>();
      ports = d.ports.map(value => {
        const p = object(value);
        if (typeof p.port !== 'number' || !Number.isInteger(p.port) || p.port < 1 || p.port > 5 || numbers.has(p.port)) throw new Error('Invalid switch port');
        numbers.add(p.port);
        return {port: p.port, connectedDevice: nullableText(p.connectedDevice), poeCapable: bool(p.poeCapable),
          connectivityCritical: bool(p.connectivityCritical), powerControlEnabled: bool(p.powerControlEnabled)};
      });
    }
    return {id, kind: d.kind as NetworkDevice['kind'], model: text(d.model), address: nullableText(d.address),
      connectedLoad: d.connectedLoad === undefined ? undefined : nullableText(d.connectedLoad),
      state: d.state as NetworkDevice['state'], output: d.output === null ? null : bool(d.output), metrics,
      stale: bool(d.stale), lastSuccessUnixMs: d.lastSuccessUnixMs as number | null,
      canSetOutput: bool(d.canSetOutput), ports};
  });
  return {schemaVersion: 1, devices, powerWritesConfigured: bool(raw.powerWritesConfigured),
    operatorAuthorizationRequired: bool(raw.operatorAuthorizationRequired)};
}

export function canControlPower(snapshot: NetworkSnapshot | null, device: NetworkDevice, token: string, fresh: boolean, busy: boolean): boolean {
  return !!snapshot?.powerWritesConfigured && snapshot.operatorAuthorizationRequired && fresh && !busy
    && device.kind === 'shelly' && device.canSetOutput && device.state === 'available' && !device.stale
    && device.output !== null && !!device.address && !!device.connectedLoad?.trim()
    && token.length >= 24 && token.length <= 512 && /^[\x20-\x7e]+$/.test(token);
}
export function parsePowerReply(value: unknown, requested: boolean): {confirmed: boolean; output: boolean} {
  const raw = object(value); const observed = object(raw.observed);
  if (raw.requestedOutput !== requested || typeof raw.confirmed !== 'boolean' || observed.state !== 'available'
    || typeof observed.output !== 'boolean') throw new Error('Invalid power readback');
  for (const value of Object.values(object(observed.metrics))) {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Invalid power metric');
  }
  return {confirmed: raw.confirmed && observed.output === requested, output: observed.output};
}
