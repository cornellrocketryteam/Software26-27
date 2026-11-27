import {useEffect, useState} from 'react';
import {parseEcoflowStatus} from './ecoflowStatus';
import type {EcoflowStatus} from './ecoflowStatus';

export default function EcoflowStatusPanel() {
  const [status, setStatus] = useState<EcoflowStatus | null>(null);
  const [error, setError] = useState(false);
  const [received, setReceived] = useState(0);
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    let stopped = false; let timer: ReturnType<typeof setTimeout>; let controller: AbortController | undefined;
    const ticker = setInterval(() => setNow(performance.now()), 1000);
    const poll = async () => {
      controller = new AbortController();
      const deadline = setTimeout(() => controller?.abort(), 2000);
      try {
        const response = await fetch('/ecoflow-api/v1/ecoflow', {cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('EcoFlow unavailable');
        const value = parseEcoflowStatus(await response.json());
        if (!stopped) {setStatus(value); setError(false); setReceived(performance.now());}
      } catch {if (!stopped) setError(true);}
      finally {clearTimeout(deadline); if (!stopped) timer = setTimeout(poll, 5000);}
    };
    void poll();
    return () => {stopped = true; clearTimeout(timer); clearInterval(ticker); controller?.abort();};
  }, []);
  const fresh = !error && received > 0 && now - received < 8000;
  const display = fresh && status?.state === 'cloud-snapshot';
  const labels = {disabled: 'Monitoring not configured', pending: 'Waiting for cloud read',
    'cloud-snapshot': 'Cloud snapshot received', 'cloud-reports-offline': 'Cloud reports power station offline',
    stale: 'Cloud reads are stale', unavailable: 'Cloud read unavailable'};
  const reading = (value: number | null | undefined, unit: string) => display && value != null ? value.toFixed(1) + unit : 'Unavailable';
  return <div className="mb-4 bg-[#D9D9D9] border-[4px] border-black rounded-2xl p-4" aria-label="EcoFlow monitoring">
    <h2 className="text-2xl font-inter font-semibold">EcoFlow RIVER 2 Pro</h2>
    <p>{fresh && status ? labels[status.state] : error ? 'EcoFlow monitoring unavailable' : 'Loading power status…'}</p>
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 my-2">
      <p>Battery: {reading(status?.batteryPercent, '%')}</p>
      <p>Total input: {reading(status?.inputWatts, ' W')}</p>
      <p>Total output: {reading(status?.outputWatts, ' W')}</p>
    </div>
    <p>Read-only cloud readings. Device sample time is unknown; these are not verified live readings or individual socket measurements.</p>
    <p>Physical electronics only. Local commanding and networking operate independently.</p>
  </div>;
}
