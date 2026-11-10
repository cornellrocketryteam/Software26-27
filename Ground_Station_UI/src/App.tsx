import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LandingPage from './LandingPage';
import PropulsionPage from './PropulsionPage';
import RecoveryPage from './RecoveryPage';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { availabilityFromMessage } from './hardwareAvailability';
import type { HardwareAvailability } from './hardwareAvailability';
import { DEFAULT_STATION_CONFIG } from './runtimeConfig';
import type { StationConfig } from './runtimeConfig';

type AppContextType = {
  hardwareAvailability: HardwareAvailability;
  hardwareAvailabilityRef: React.RefObject<HardwareAvailability>;
  wsRef: React.RefObject<WebSocket | null>;
  currFlightMode: FlightMode;
  setCurrFlightMode: (flightMode: FlightMode) => void;
  uri: string;
  wsReady: boolean;
  hasLaunched: boolean;
  setHasLaunched: (launched: boolean) => void;
  stationConfig?: StationConfig;
}
export type FlightMode = "....."| 'Standby' | 'Startup' | 'Ascent' | 'Coast' | 'DrogueDeployed' | 'MainDeployed' | 'Fault';

export const AppContext = createContext<AppContextType | null>(null);

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) throw new Error("useAppContext must be used inside App");
  return context;
};



function App({ config = DEFAULT_STATION_CONFIG, configError = null }: {
  config?: StationConfig; configError?: string | null;
}) {
  const wsRef = useRef<WebSocket | null>(null);
  const [hardwareAvailability, setHardwareAvailability] = useState<HardwareAvailability>(null);
  const hardwareAvailabilityRef = useRef<HardwareAvailability>(null);

  const uri = config.fillStationWebSocketUrl ?? '';
  const [wsReady, setWsReady] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [currFlightMode, setCurrFlightMode] = useState<FlightMode>('.....');

  // Track whether we've launched. Backed by sessionStorage so the locked-out launch
  // state survives a page refresh, but auto-clears when the tab closes (a new session
  // starts unlocked, rather than latching forever as localStorage would).
  const [hasLaunched, setHasLaunched] = useState(() => sessionStorage.getItem('hasLaunched') === 'true');

  const handleMessage = useCallback((event: MessageEvent) => {
    let data;
    try { data = JSON.parse(event.data); }
    catch { return; }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return;
    const availability = availabilityFromMessage(data);
    if (availability !== undefined) {
      hardwareAvailabilityRef.current = availability;
      setHardwareAvailability(availability);
    }
    if(data.type === "fsw_telemetry" && typeof data.flight_mode === 'string'){
      setCurrFlightMode(data.flight_mode as FlightMode);
    }
  }, []);
  
  useEffect(() => {
        let reconnectTimeout: ReturnType<typeof setTimeout>;
        let heartbeatInterval: ReturnType<typeof setInterval>;
        let disposed = false;
        let socket: WebSocket | null = null;
        if (!uri) return;

        const connect = () => {
          if (disposed) return;
          hardwareAvailabilityRef.current = null;
          setHardwareAvailability(null);
          let active: WebSocket;
          try { active = new WebSocket(uri); }
          catch {
            setWsReady(false);
            setConnectionError('Fill-station connection could not be opened. Check its address and browser permissions.');
            return;
          }
          setConnectionError(null);
          socket = active;
          wsRef.current = active;

          active.onopen = () => {
                if (disposed || wsRef.current !== active) return;
                console.log("WebSocket connection established.");
                setWsReady(true);
                active.send(JSON.stringify({command:"get_hardware_availability"}));
                // Global heartbeat — keeps the connection alive on every page.
                // Server disconnects after 15s without one (main.rs:231).
                heartbeatInterval = setInterval(() => {
                    if (!disposed && active.readyState === WebSocket.OPEN) {
                        active.send(JSON.stringify({ "command": "heartbeat" }));
                        console.log("Sent Heartbeat");
                    }
                }, 5000);
            };

            active.onclose = () => {
                if (disposed || wsRef.current !== active) return;
                wsRef.current = null;
                console.log("WebSocket closed. Reconnecting in 3 seconds...");
                clearInterval(heartbeatInterval);
                setWsReady(false);
                hardwareAvailabilityRef.current = null;
                setHardwareAvailability(null);
                reconnectTimeout = setTimeout(connect, 3000);
            };

            active.onerror = (error) => {
                console.error("WebSocket error:", error);
                active.close();
            };
            active.addEventListener('message', handleMessage);
        };

        connect();

        return () => {
            disposed = true;
            clearInterval(heartbeatInterval);
            clearTimeout(reconnectTimeout);
            if (socket) {
              socket.removeEventListener('message', handleMessage);
              socket.onclose = null;
              socket.onerror = null;
              socket.close();
              if (wsRef.current === socket) wsRef.current = null;
            }
        };
    }, [uri, handleMessage]);
  return (
    <AppContext.Provider value={{hardwareAvailability, hardwareAvailabilityRef, hasLaunched, setHasLaunched, setCurrFlightMode, currFlightMode, wsRef, uri: uri, wsReady, stationConfig: config}}>
      <aside role="status" className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b-2 border-black bg-[#F9F9EB] px-8 py-2 text-sm font-semibold">
        <span>Fill station: {!uri ? 'not configured' : wsReady ? 'connected' : 'disconnected'}</span>
        {!config.map.tilesConfigured && <span>Offline maps: not configured</span>}
        {(configError || connectionError) && <span role="alert">{configError || connectionError}</span>}
        {config.grafanaUrl && <a href={config.grafanaUrl} target="_blank" rel="noopener noreferrer" className="underline">Grafana</a>}
      </aside>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/propulsion" element={<PropulsionPage />} />
          <Route path="/recovery" element={<RecoveryPage />} />
        </Routes>
      </BrowserRouter>
    </AppContext.Provider>

  );
}

export default App;
