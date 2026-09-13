import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet-draw";
import type { Region } from "./types";

type Props = {
  region: Region;
  onChange: (region: Region) => void;
};

export default function RegionPicker({ region, onChange }: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.FeatureGroup | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!elementRef.current || mapRef.current) return;
    const map = L.map(elementRef.current, { minZoom: 1 }).setView([35, 0], 1);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 18,
    }).addTo(map);
    const layers = L.featureGroup().addTo(map);
    map.addControl(
      new L.Control.Draw({
        draw: {
          rectangle: { shapeOptions: { color: "#16b8a6", weight: 2 } },
          polygon: false,
          polyline: false,
          circle: false,
          circlemarker: false,
          marker: false,
        },
        edit: { featureGroup: layers, remove: false },
      }),
    );
    map.on(L.Draw.Event.CREATED, (event) => {
      const createdEvent = event as L.DrawEvents.Created;
      layers.clearLayers();
      layers.addLayer(createdEvent.layer);
      const bounds = (createdEvent.layer as L.Rectangle).getBounds();
      onChangeRef.current({
        west: Number(bounds.getWest().toFixed(3)),
        east: Number(bounds.getEast().toFixed(3)),
        south: Number(bounds.getSouth().toFixed(3)),
        north: Number(bounds.getNorth().toFixed(3)),
      });
    });
    mapRef.current = map;
    layerRef.current = layers;
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const layers = layerRef.current;
    if (!layers || region.west >= region.east || region.south >= region.north) return;
    layers.clearLayers();
    layers.addLayer(
      L.rectangle(
        [
          [region.south, region.west],
          [region.north, region.east],
        ],
        { color: "#16b8a6", weight: 2 },
      ),
    );
  }, [region]);

  return (
    <section className="map-panel" aria-label="Query region map">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Query domain</p>
          <h2>Select a region</h2>
        </div>
        <span className="map-hint">Use the rectangle tool or enter bounds below</span>
      </div>
      <div className="map" ref={elementRef} />
    </section>
  );
}
