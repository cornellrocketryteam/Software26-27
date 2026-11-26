import {useEffect, useState} from 'react';
import {parseWanStatus} from './wanStatus';
import type {WanStatus} from './wanStatus';

export default function WanStatusPanel() {
  const [status, setStatus] = useState<WanStatus | null>(null);
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
        const response = await fetch('/network-api/v1/wan', {cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('WAN status unavailable');
        const value = parseWanStatus(await response.json());
        if (!stopped) {setStatus(value); setError(false); setReceived(performance.now());}
      } catch {if (!stopped) setError(true);}
      finally {clearTimeout(deadline); if (!stopped) timer = setTimeout(poll, 5000);}
    };
    void poll();
    return () => {stopped = true; clearTimeout(timer); clearInterval(ticker); controller?.abort();};
  }, []);
  const fresh = !error && received > 0 && now - received < 8000;
  const current = fresh && !!status && status.state !== 'stale' && status.state !== 'pending';
  const labels = {disabled: 'Monitoring not configured', pending: 'Waiting for first probes',
    reachable: 'At least one TCP connection succeeded', unreachable: 'No TCP connections succeeded', stale: 'Probe observations are stale'};
  return <div className="mb-4 bg-[#D9D9D9] border-[4px] border-black rounded-2xl p-4">
    <h2 className="text-2xl font-inter font-semibold">WAN probes</h2>
    <p>{fresh && status ? labels[status.state] : error ? 'Monitoring unavailable' : 'Loading probe status…'}</p>
    <p className="my-2">Optional external TCP probes. These are not Starlink radio metrics or packet-loss measurements.</p>
    {status?.enabled && <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {status.targets.map(target => <div key={target.address + ':' + target.port} className="bg-white border-2 border-black rounded-xl p-3">
        <h3 className="font-semibold">{target.label}</h3>
        <p>{target.address}:{target.port}</p>
        <p>Last TCP connect: {current && target.connectMs !== null ? target.connectMs.toFixed(1) + ' ms' : 'Unavailable'}</p>
        <p>Recent probe failures: {current && target.attempts ? target.failures + '/' + target.attempts : 'Unavailable'}</p>
      </div>)}
    </div>}
    {status?.enabled && <p className="mt-2">Observed consecutive failed-round span: {current && status.observedFailureSpanSeconds !== null ? status.observedFailureSpanSeconds.toFixed(0) + ' s' : 'Unavailable'}. This is not the full outage duration.</p>}
    <p className="mt-2">Local telemetry, commanding and device controls do not require these targets.</p>
  </div>;
}
