// Manual browser regression fixture. All commands remain inside this page.
import React, {useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MemoryRouter} from 'react-router-dom';
import {AppContext} from '../src/App';
import {PropulsionPage} from '../src/PropulsionPage';
import type {HardwareAvailability} from '../src/hardwareAvailability';
import '../src/index.css';
class LocalSocket extends EventTarget {
  readyState = 1;
  sent: string[] = [];
  send(message: string) { this.sent.push(message); }
}
function Fixture() {
  const [availability, setAvailability] = useState<HardwareAvailability>({availability_version:1,configured_devices_mask:4095});
  const availabilityRef = useRef(availability);
  const wsRef = useRef(new LocalSocket() as unknown as WebSocket);
  const [connected,setConnected] = useState(true);
  const [hasLaunched,setHasLaunched] = useState(false);
  const [ventCount,setVentCount] = useState(0);
  const setMask = (mask: number) => {
    const value={availability_version:1,configured_devices_mask:mask};
    availabilityRef.current=value;setAvailability(value);
  };
  return <AppContext.Provider value={{hardwareAvailability:availability,hardwareAvailabilityRef:availabilityRef,wsRef,currFlightMode:'Standby',setCurrFlightMode:()=>{},uri:'fixture://no-network',wsReady:connected,hasLaunched,setHasLaunched}}>
    <div style={{padding:8,border:'3px solid teal',position:'sticky',top:0,background:'white',zIndex:100}}>
      <strong>Local fixture — no hardware connection</strong>{' '}
      <button onClick={()=>setMask(4095)}>All devices</button>{' '}
      <button onClick={()=>setMask(4095 & ~(1<<10))}>Disable ball valve</button>{' '}
      <button onClick={()=>{(wsRef.current as unknown as LocalSocket).readyState=3;setConnected(false);}}>Disconnect fixture</button>{' '}
      <button onClick={()=>{(wsRef.current as unknown as LocalSocket).readyState=1;setConnected(true);}}>Reconnect fixture</button>{' '}
      <button onClick={()=>setVentCount((wsRef.current as unknown as LocalSocket).sent.filter(message=>JSON.parse(message).command==='fsw_close_sv').length)}>Count FSW closes</button>{' '}
      <output>FSW closes: {ventCount}</output>
    </div>
    <PropulsionPage />
  </AppContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><MemoryRouter><Fixture /></MemoryRouter></React.StrictMode>);
