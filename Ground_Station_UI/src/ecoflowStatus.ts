export type EcoflowStatus = {
  enabled: boolean; state: 'disabled' | 'pending' | 'cloud-snapshot' | 'cloud-reports-offline' | 'stale' | 'unavailable';
  ageSeconds: number | null; batteryPercent: number | null; inputWatts: number | null; outputWatts: number | null;
};
export function parseEcoflowStatus(raw: unknown): EcoflowStatus {
  if (!raw || typeof raw !== 'object') throw new Error('Invalid EcoFlow status');
  const v = raw as Record<string, unknown>;
  const states = ['disabled', 'pending', 'cloud-snapshot', 'cloud-reports-offline', 'stale', 'unavailable'];
  if (typeof v.enabled !== 'boolean' || !states.includes(v.state as string) || v.readOnly !== true || v.deviceSampleTimeKnown !== false || v.enabled === (v.state === 'disabled')) throw new Error('Invalid EcoFlow state');
  const metric = (key: string, max: number) => {
    const x = v[key];
    if (x !== null && (typeof x !== 'number' || !Number.isFinite(x) || x < 0 || x > max)) throw new Error('Invalid EcoFlow metric');
    return x as number | null;
  };
  const ageSeconds = metric('ageSeconds', Number.MAX_VALUE);
  const batteryPercent = metric('batteryPercent', 100), inputWatts = metric('inputWatts', 10000), outputWatts = metric('outputWatts', 10000);
  if (v.state !== 'cloud-snapshot' && [batteryPercent, inputWatts, outputWatts].some(x => x !== null)) throw new Error('Inactive EcoFlow readings');
  if (v.state === 'cloud-snapshot' && ageSeconds === null) throw new Error('Missing cloud age');
  return {enabled: v.enabled, state: v.state as EcoflowStatus['state'], ageSeconds, batteryPercent, inputWatts, outputWatts};
}
