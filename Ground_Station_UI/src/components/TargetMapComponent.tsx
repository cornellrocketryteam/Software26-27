import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { DEFAULT_STATION_CONFIG } from '../runtimeConfig';
import type { StationConfig } from '../runtimeConfig';

export type TargetCoords = {
    lat_1: string;
    lng_1: string;
    lat_2: string;
    lng_2: string;
    lat_3: string;
    lng_3: string;
};

type ParsedTarget = {
    label: string;
    position: [number, number];
    color: string;
};

/**
 * Build a small, color-coded teardrop marker as an inline SVG. Using a divIcon
 * avoids Leaflet's default-marker image paths breaking under the Vite bundler.
 */
const makeMarkerIcon = (color: string, label: string) =>
    L.divIcon({
        className: "",
        html: `
            <div style="position:relative;display:flex;flex-direction:column;align-items:center;">
                <div style="
                    width:22px;height:22px;border-radius:50% 50% 50% 0;
                    background:${color};border:3px solid #000;
                    transform:rotate(-45deg);box-shadow:0 1px 3px rgba(0,0,0,0.4);">
                </div>
                <span style="
                    position:absolute;top:2px;color:#fff;font-family:inherit;
                    font-weight:700;font-size:11px;">${label}</span>
            </div>`,
        iconSize: [22, 30],
        iconAnchor: [11, 30],
        popupAnchor: [0, -30],
    });


// Keeps the map framed around the confirmed targets. We key the effect off the
function FitBounds({ targets }: { targets: ParsedTarget[] }) {
    const map = useMap();
    const positionsKey = targets.map((t) => t.position.join(",")).join("|");
    useEffect(() => {
        if (targets.length === 0) return;
        if (targets.length === 1) {
            map.setView(targets[0].position, 15);
        } else {
            map.fitBounds(
                L.latLngBounds(targets.map((t) => t.position)),
                { padding: [60, 60], maxZoom: 16 }
            );
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [map, positionsKey]);
    return null;
}

type TargetMapProps = {
    coords: TargetCoords | null;
    /** Tailwind height class for the map container. */
    heightClass?: string;
    mapConfig?: StationConfig['map'];
};

/**
 * Renders confirmed recovery target coordinates on an interactive map
 * Self-contained and prop-driven — it is simple to drop it into any page (or remove it) freely.
 */
export function TargetMap({ coords, heightClass = "h-96", mapConfig = DEFAULT_STATION_CONFIG.map }: TargetMapProps) {
    const [tileLoadFailed, setTileLoadFailed] = useState(false);
    const tileLayer = useRef<L.TileLayer | null>(null);
    const targets: ParsedTarget[] = [
        { label: "U", lat: coords?.lat_1, lng: coords?.lng_1, color: "#5A87FF" }, //Upwind Location
        { label: "D", lat: coords?.lat_2, lng: coords?.lng_2, color: "#FF6B5A" }, //Downwind Location
        { label: "B", lat: coords?.lat_3, lng: coords?.lng_3, color: "#8A9A5B" }, //Current Location
    ]
        .map(({ label, lat, lng, color }) => ({
            label,
            color,
            position: [Number(lat), Number(lng)] as [number, number],
        }))
        .filter(
            (t) => !Number.isNaN(t.position[0]) && !Number.isNaN(t.position[1])
        );

    if (targets.length === 0) {
        return (
            <div className={`${heightClass} flex items-center justify-center rounded-2xl border-[3px] border-black bg-white font-inter text-lg text-gray-500`}>
                Confirm coordinates to view targets on the map.
            </div>
        );
    }

    if (!mapConfig.tilesConfigured) {
        return <div className={`${heightClass} flex items-center justify-center rounded-2xl border-[3px] border-black bg-white font-inter text-lg text-gray-500`}>
            Offline map tiles are not configured.
        </div>;
    }

    return (
        <div className={`${heightClass} relative overflow-hidden rounded-2xl border-[3px] border-black`}>
            {tileLoadFailed && <div role="status" className="absolute inset-x-0 top-0 z-[500] flex items-center justify-center gap-3 bg-white px-4 py-2 text-sm">
                <span>Some map tiles could not be loaded.</span>
                <button type="button" className="rounded border border-black px-2 py-1" onClick={() => {
                    setTileLoadFailed(false);
                    tileLayer.current?.redraw();
                }}>Retry map tiles</button>
            </div>}
            <MapContainer
                center={targets[0].position}
                zoom={15}
                scrollWheelZoom
                style={{ height: "100%", width: "100%" }}
            >
                <TileLayer
                    ref={tileLayer}
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                    url={mapConfig.tileUrl}
                    eventHandlers={{ tileerror: () => setTileLoadFailed(true) }}
                />
                {targets.map((t) => (
                    <Marker
                        key={t.label}
                        position={t.position}
                        icon={makeMarkerIcon(t.color, t.label)}
                    >
                        <Popup>
                            <span className="font-inter font-bold">
                                Target {t.label}
                            </span>
                            <br />
                            Lat: {t.position[0]}°
                            <br />
                            Lon: {t.position[1]}°
                        </Popup>
                    </Marker>
                ))}
                {targets.length === 3 && (
                    <Polyline
                        positions={[targets[0].position, targets[1].position]}
                        pathOptions={{ color: "#000", weight: 2, dashArray: "6 6" }}
                    />
                )}
                <FitBounds targets={targets} />
            </MapContainer>
        </div>
    );
}

export default TargetMap;
