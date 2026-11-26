export type WanTarget = {label: string; address: string; port: number; reachable: boolean | null; connectMs: number | null;
  attempts: number; failures: number; failureFraction: number | null; meanSuccessfulConnectMs: number | null};
export type WanStatus = {enabled: boolean; state: 'disabled' | 'pending' | 'reachable' | 'unreachable' | 'stale';
  checkedUnixMs: number | null; ageSeconds: number | null; observedFailureSpanSeconds: number | null; targets: WanTarget[]};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid WAN response');
  return value as Record<string, unknown>;
}
function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw new Error('Invalid WAN metric');
  return value;
}
function optional(value: unknown): number | null {return value === null ? null : number(value);}
export function parseWanStatus(value: unknown): WanStatus {
  const raw = object(value);
  if (raw.method !== 'tcp-connect' || typeof raw.enabled !== 'boolean'
    || !['disabled', 'pending', 'reachable', 'unreachable', 'stale'].includes(String(raw.state))
    || !Array.isArray(raw.targets) || raw.targets.length > 3) throw new Error('Invalid WAN response');
  if ((!raw.enabled && (raw.state !== 'disabled' || raw.targets.length !== 0)) || (raw.enabled && (raw.state === 'disabled' || !raw.targets.length))) throw new Error('Invalid WAN configuration');
  const targets = raw.targets.map((item): WanTarget => {
    const t = object(item);
    if (typeof t.label !== 'string' || !t.label || typeof t.address !== 'string'
      || typeof t.port !== 'number' || !Number.isInteger(t.port) || t.port < 1 || t.port > 65535
      || (t.reachable !== null && typeof t.reachable !== 'boolean')) throw new Error('Invalid WAN target');
    const attempts = number(t.attempts); const failures = number(t.failures);
    const fraction = optional(t.failureFraction); const timing = optional(t.connectMs);
    if (!Number.isInteger(attempts) || attempts > 30 || !Number.isInteger(failures) || failures > attempts
      || (fraction !== null && fraction > 1) || (t.reachable !== true && timing !== null)) throw new Error('Invalid WAN observations');
    return {label: t.label, address: t.address, port: t.port, reachable: t.reachable as boolean | null,
      connectMs: timing, attempts, failures, failureFraction: fraction, meanSuccessfulConnectMs: optional(t.meanSuccessfulConnectMs)};
  });
  if ((raw.state === 'reachable' && !targets.some(target => target.reachable === true))
    || (raw.state === 'unreachable' && !targets.every(target => target.reachable === false))) throw new Error('Inconsistent WAN connection state');
  return {enabled: raw.enabled, state: raw.state as WanStatus['state'], targets,
    checkedUnixMs: optional(raw.checkedUnixMs), ageSeconds: optional(raw.ageSeconds),
    observedFailureSpanSeconds: optional(raw.observedFailureSpanSeconds)};
}
