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
  mask=4095;
  states={SV1:false,BV:false};
  send(message: string) {
    this.sent.push(message);
    const m=JSON.parse(message);
    if (m.command==='actuate_valve' && m.valve==='SV1') this.states.SV1=m.open;
    if (m.command==='bv_open' || m.command==='bv_close') this.states.BV=m.command==='bv_open';
    const reply = m.command==='get_hardware_availability'
      ? {type:'hardware_availability',availability_version:1,configured_devices_mask:this.mask}
      : m.command==='get_valve_state' ? {type:'valve_state',valve:'SV1',open:this.states.SV1,continuity:true}
      : m.command==='get_ball_valve_state' ? {type:'ball_valve_state',open:this.states.BV} : null;
    if (reply) queueMicrotask(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(reply)})));
  }
}
function Fixture() {
  const [availability, setAvailability] = useState<HardwareAvailability>({availability_version:1,configured_devices_mask:4095});
  const availabilityRef = useRef(availability);
  const wsRef = useRef(new LocalSocket() as unknown as WebSocket);
  const [connected,setConnected] = useState(true);
  const [hasLaunched,setHasLaunched] = useState(false);
  const [commandCount,setCommandCount] = useState(0);
  const setMask = (mask: number) => {
    const value={availability_version:1,configured_devices_mask:mask};
    availabilityRef.current=value;setAvailability(value);
    const socket=wsRef.current as unknown as LocalSocket;
    socket.mask=mask;
    socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'hardware_availability',...value})}));
  };
  return <AppContext.Provider value={{operatingProfile:'legacy',operatingProfileRef:{current:'legacy'},hardwareAvailability:availability,hardwareAvailabilityRef:availabilityRef,wsRef,currFlightMode:'Standby',setCurrFlightMode:()=>{},uri:'fixture://no-network',wsReady:connected,hasLaunched,setHasLaunched}}>
    <div style={{padding:8,border:'3px solid teal',position:'sticky',top:0,background:'white',zIndex:100}}>
      <strong>Local fixture — no hardware connection</strong>{' '}
      <button onClick={()=>setMask(4095)}>All devices</button>{' '}
      <button onClick={()=>setMask(4095 & ~(1<<10))}>Disable ball valve</button>{' '}
      <button onClick={()=>{(wsRef.current as unknown as LocalSocket).readyState=3;setConnected(false);}}>Disconnect fixture</button>{' '}
      <button onClick={()=>{(wsRef.current as unknown as LocalSocket).readyState=1;setConnected(true);}}>Reconnect fixture</button>{' '}
      <button onClick={()=>setCommandCount((wsRef.current as unknown as LocalSocket).sent.filter(message=>['actuate_valve','bv_open','bv_close'].includes(JSON.parse(message).command)).length)}>Count manual requests</button>{' '}
      <output>Manual requests: {commandCount}</output>
    </div>
    <PropulsionPage />
  </AppContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><MemoryRouter><Fixture /></MemoryRouter></React.StrictMode>);
