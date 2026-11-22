import {useEffect, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import crtLogo from './assets/CRT_LOGO.png';
import {parseNetworkSnapshot} from './networkDevices';
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
  const [error, setError] = useState('');
  const [receivedAt, setReceivedAt] = useState(0);
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController | undefined;
    const tick = setInterval(() => setNow(performance.now()), 1000);
    const poll = async () => {
      controller = new AbortController();
      const deadline = setTimeout(() => controller?.abort(), 7000);
      try {
        const response = await fetch('/network-api/v1/devices', {cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('Network device service is unavailable.');
        const value = parseNetworkSnapshot(await response.json());
        if (!stopped) {setSnapshot(value); setReceivedAt(performance.now()); setError('');}
      } catch {
        if (!stopped) setError('Network device service is unavailable or returned invalid data.');
      } finally {
        clearTimeout(deadline);
        if (!stopped) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => {stopped = true; clearTimeout(timer); clearInterval(tick); controller?.abort();};
  }, []);
  const fresh = !error && receivedAt > 0 && now - receivedAt < 8000;
  return <div className="min-h-screen bg-white">
    <header className="bg-[#F9F9EB] px-8 py-4 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/stations')} aria-label="Go to stations"><img src={crtLogo} alt="CRT Logo" className="h-16" /></button>
        <h1 className="text-4xl font-inter">Network devices</h1>
      </div>
      <button onClick={() => navigate('/stations')} className="bg-white border-[4px] border-black rounded-3xl px-6 py-2 text-lg font-inter">Back to stations</button>
    </header>
    <main className="p-4 sm:p-8">
      <p className="mb-4">Read-only device status and wiring. Power controls will be added after device setup and verification.</p>
      {error && <p role="alert" className="mb-4 font-semibold">{error} {snapshot ? 'Previous readings are not current.' : ''}</p>}
      {!snapshot && !error && <p role="status">Loading device inventory…</p>}
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
