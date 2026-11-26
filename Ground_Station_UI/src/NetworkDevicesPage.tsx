import {useEffect, useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import crtLogo from './assets/CRT_LOGO.png';
import WanStatusPanel from './WanStatusPanel';
import {canControlPower, parseNetworkSnapshot, parsePowerReply} from './networkDevices';
import type {NetworkSnapshot} from './networkDevices';

const stateLabels = {
  not_configured: 'Not configured', inspection_pending: 'Management inspection pending',
  available: 'Available', unavailable: 'Unavailable', unknown: 'Unknown outcome',
};
const metrics: Record<string, [string, string]> = {
  powerW: ['Power', 'W'], voltageV: ['Voltage', 'V'], currentA: ['Current', 'A'], energyWh: ['Energy', 'Wh'],
};

export default function NetworkDevicesPage() {
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<NetworkSnapshot | null>(null);
  const [token, setToken] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{id: string; address: string; load: string; on: boolean} | null>(null);
  const epoch = useRef(0); const writing = useRef(false); const mounted = useRef(false);
  const postController = useRef<AbortController | null>(null);
  const [error, setError] = useState('');
  const [receivedAt, setReceivedAt] = useState(0);
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    let stopped = false; mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController | undefined;
    const tick = setInterval(() => setNow(performance.now()), 1000);
    const poll = async () => {
      if (writing.current) {timer = setTimeout(poll, 3000); return;}
      const requestEpoch = epoch.current;
      controller = new AbortController();
      const deadline = setTimeout(() => controller?.abort(), 7000);
      try {
        const response = await fetch('/network-api/v1/devices', {cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('Network device service is unavailable.');
        const value = parseNetworkSnapshot(await response.json());
        if (!stopped && requestEpoch === epoch.current) {setSnapshot(value); setReceivedAt(performance.now()); setError(''); if (!value.powerWritesConfigured) {setToken(''); setPending(null);}}
      } catch {
        if (!stopped && requestEpoch === epoch.current) {setError('Network device service is unavailable or returned invalid data.'); setToken(''); setPending(null);}
      } finally {
        clearTimeout(deadline);
        if (!stopped) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => {stopped = true; mounted.current = false; postController.current?.abort(); clearTimeout(timer); clearInterval(tick); controller?.abort();};
  }, []);
  const fresh = !error && receivedAt > 0 && now - receivedAt < 8000;
  const confirmPower = async () => {
    const action = pending;
    const device = snapshot?.devices.find(value => value.id === action?.id);
    const current = !error && receivedAt > 0 && performance.now() - receivedAt < 8000;
    setPending(null);
    if (!action || !device || !canControlPower(snapshot, device, token, current, writing.current)
      || device.address !== action.address || device.connectedLoad !== action.load || device.output === action.on) {
      setNotice('Power request cancelled: status or device configuration changed.'); return;
    }
    writing.current = true; epoch.current++; setBusy(true); setReceivedAt(0);
    const controller = new AbortController(); postController.current = controller;
    const deadline = setTimeout(() => controller.abort(), 8000);
    setNotice('Sending explicit power request; awaiting relay readback…');
    try {
      const response = await fetch(`/network-api/v1/devices/${encodeURIComponent(action.id)}/output`, {
        method: 'POST', redirect: 'error', credentials: 'omit', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', Authorization: `Bearer ${token}`},
        body: JSON.stringify({on: action.on}),
      });
      if (response.status === 403) {
        if (mounted.current) {setToken(''); setNotice('Operator authorization rejected. Controls locked.');} return;
      }
      if (response.status === 409) {
        if (mounted.current) setNotice('Device busy; no power request dispatched. Wait for fresh status before confirming again.');
        return;
      }
      if (!response.ok) throw new Error('Power outcome unknown');
      const reply = parsePowerReply(await response.json(), action.on);
      if (mounted.current) {
        setNotice(reply.confirmed ? `Relay reported ${reply.output ? 'On' : 'Off'}. Waiting for fresh status; this does not prove the attached load is operating.`
          : `Request not confirmed: relay reported ${reply.output ? 'On' : 'Off'}. Inspect before another request.`);
        if (!reply.confirmed) setToken('');
      }
    } catch {
      if (mounted.current) {setToken(''); setNotice('Power outcome unknown. Controls locked; inspect fresh relay status before another request. No automatic retry.');}
    } finally {
      clearTimeout(deadline); writing.current = false; postController.current = null;
      if (mounted.current) {setBusy(false); setReceivedAt(0);}
    }
  };
  return <div className="min-h-screen bg-white">
    <header className="bg-[#F9F9EB] px-8 py-4 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/stations')} aria-label="Go to stations"><img src={crtLogo} alt="CRT Logo" className="h-16" /></button>
        <h1 className="text-4xl font-inter">Network devices</h1>
      </div>
      <button onClick={() => navigate('/stations')} className="bg-white border-[4px] border-black rounded-3xl px-6 py-2 text-lg font-inter">Back to stations</button>
    </header>
    <main className="p-4 sm:p-8">
      <p className="mb-4">Device status and recorded wiring. Shelly power requests require configured loads, fresh status and operator authorization.</p>
      <WanStatusPanel />
      {error && <p role="alert" className="mb-4 font-semibold">{error} {snapshot ? 'Previous readings are not current.' : ''}</p>}
      {!snapshot && !error && <p role="status">Loading device inventory…</p>}
      <div className="mb-4 bg-[#D9D9D9] border-[4px] border-black rounded-2xl p-4">
        <label className="block">Operator token (this page only)
          <input type="password" autoComplete="off" maxLength={512} value={token} disabled={!snapshot?.powerWritesConfigured || busy}
            onChange={event => {setToken(event.target.value); setPending(null);}}
            className="bg-white border-2 border-black rounded-lg px-3 py-2 ml-2" />
        </label>
        <button disabled={busy} onClick={() => {setToken(''); setPending(null);}} className="mt-2 border-2 border-black rounded-xl px-4 py-2 bg-white">Lock controls</button>
        <p>{snapshot?.powerWritesConfigured ? 'Authorization is checked by the server for each request. Token is not saved.' : 'Power writes are not configured on the server.'}</p>
      </div>
      {notice && <p role="status" className="mb-4 font-semibold">{notice}</p>}
      {pending && <div role="dialog" aria-modal="true" aria-label="Confirm plug power" className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
        <div className="bg-[#D9D9D9] border-[6px] border-black rounded-3xl p-6 max-w-lg">
          <h2 className="text-2xl font-semibold">Turn {pending.on ? 'On' : 'Off'} {pending.id}?</h2>
          <p>{pending.load} · {pending.address}</p>
          <p className="my-3">This sends an immediate relay request. Confirm the connected load is ready.</p>
          <button onClick={() => void confirmPower()} className="bg-[#E27D7D] border-[4px] border-black rounded-xl px-4 py-2 mr-3">Confirm power request</button>
          <button onClick={() => setPending(null)} className="bg-white border-[4px] border-black rounded-xl px-4 py-2">Cancel</button>
        </div>
      </div>}
      {snapshot && <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {snapshot.devices.map(device => {
          const current = fresh && !device.stale;
          return <section key={device.id} aria-label={device.id} className="bg-[#D9D9D9] border-[6px] border-black rounded-3xl p-5 min-w-0">
            <h2 className="text-2xl font-inter font-semibold break-words">{device.id}</h2>
            <p>{device.model} · {device.address ?? 'Address not configured'}</p>
            <p className="font-semibold my-2">{fresh ? device.state === 'available' && device.stale ? 'Stale readings' : stateLabels[device.state] : 'Status unavailable'}</p>
            <div className="bg-white border-[4px] border-black rounded-2xl p-4">
              {device.kind === 'shelly' ? <>
                <p>Connected load: {device.connectedLoad ?? 'Not assigned'}</p>
                <p>Relay report: {current && device.output !== null ? device.output ? 'On' : 'Off' : 'Unknown'}</p>
                <div className="flex flex-wrap gap-3 my-3">{[true, false].map(on => <button key={String(on)}
                  disabled={!canControlPower(snapshot, device, token, fresh, busy) || device.output === on}
                  onClick={() => setPending({id: device.id, address: device.address!, load: device.connectedLoad!, on})}
                  className="bg-white border-[4px] border-black rounded-xl px-4 py-2 disabled:opacity-40">
                  Turn {on ? 'on' : 'off'}
                </button>)}</div>
                {Object.entries(metrics).map(([key, [label, unit]]) => <p key={key}>{label}: {current && device.metrics[key] !== undefined ? `${device.metrics[key]} ${unit}` : 'Unavailable'}</p>)}
              </> : <p>Live metrics are pending management-interface inspection.</p>}
              {device.ports && <div className="overflow-x-auto mt-3"><table className="w-full text-left">
                <caption className="text-left font-semibold mb-2">Recorded port wiring · not live port state</caption>
                <thead><tr><th className="pr-3">Port</th><th className="pr-3">Connection</th><th>Capability</th></tr></thead>
                <tbody>{device.ports.map(port => <tr key={port.port}>
                  <td className="pr-3">{port.port}</td><td className="pr-3">{port.connectedDevice ?? 'Unassigned'}{port.connectivityCritical ? ' · Infrastructure' : ''}</td>
                  <td>{port.poeCapable ? 'PoE-capable' : 'Non-PoE'}</td>
                </tr>)}</tbody>
              </table></div>}
            </div>
          </section>;
        })}
      </div>}
    </main>
  </div>;
}
