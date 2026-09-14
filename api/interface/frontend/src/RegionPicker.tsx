import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet-draw";
import type { Region } from "./types";

type Props = {
  region: Region;
  onChange: (region: Region) => void;
};

type Selection = {
  enabled: boolean;
  start: L.LatLng | null;
  pointerDown: boolean;
  moved: boolean;
};

const emptySelection = (): Selection => ({
  enabled: false,
  start: null,
  pointerDown: false,
  moved: false,
});

function regionFromBounds(bounds: L.LatLngBounds): Region {
  return {
    west: Number(bounds.getWest().toFixed(3)),
    east: Number(bounds.getEast().toFixed(3)),
    south: Number(bounds.getSouth().toFixed(3)),
    north: Number(bounds.getNorth().toFixed(3)),
  };
}

export default function RegionPicker({ region, onChange }: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.FeatureGroup | null>(null);
  const previewRef = useRef<L.Rectangle | null>(null);
  const selectionRef = useRef<Selection>(emptySelection());
  const onChangeRef = useRef(onChange);
  const [selecting, setSelecting] = useState(false);
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
        draw: false as unknown as L.Control.DrawOptions,
        edit: { featureGroup: layers, remove: false },
      }),
    );

    const updateFromLayer = (layer: L.Layer) => {
      if (!(layer instanceof L.Rectangle)) return;
      const next = regionFromBounds(layer.getBounds());
      if (next.west < next.east && next.south < next.north) {
        onChangeRef.current(next);
      }
    };

    map.on(L.Draw.Event.EDITED, (event) => {
      const edited = event as L.DrawEvents.Edited;
      edited.layers.eachLayer(updateFromLayer);
    });

    const finishSelection = (end: L.LatLng) => {
      const selection = selectionRef.current;
      if (!selection.start) return;
      const bounds = L.latLngBounds(selection.start, end);
      const next = regionFromBounds(bounds);
      if (next.west === next.east || next.south === next.north) return;
      layers.clearLayers();
      layers.addLayer(
        L.rectangle(bounds, { color: "#16b8a6", weight: 2, fillOpacity: 0.12 }),
      );
      previewRef.current = null;
      selectionRef.current = emptySelection();
      map.dragging.enable();
      map.getContainer().classList.remove("drawing-region");
      setSelecting(false);
      onChangeRef.current(next);
    };

    map.on("mousedown", (event: L.LeafletMouseEvent) => {
      const selection = selectionRef.current;
      if (!selection.enabled) return;
      selection.pointerDown = true;
      selection.moved = false;
      if (!selection.start) selection.start = event.latlng;
    });
    map.on("mousemove", (event: L.LeafletMouseEvent) => {
      const selection = selectionRef.current;
      if (!selection.enabled || !selection.start || !selection.pointerDown) return;
      selection.moved = true;
      const bounds = L.latLngBounds(selection.start, event.latlng);
      if (previewRef.current) previewRef.current.setBounds(bounds);
      else {
        previewRef.current = L.rectangle(bounds, {
          color: "#16b8a6",
          weight: 2,
          dashArray: "5 4",
          fillOpacity: 0.12,
        }).addTo(map);
      }
    });
    map.on("mouseup", (event: L.LeafletMouseEvent) => {
      const selection = selectionRef.current;
      if (!selection.enabled || !selection.start) return;
      selection.pointerDown = false;
      if (selection.moved) finishSelection(event.latlng);
    });
    map.on("click", (event: L.LeafletMouseEvent) => {
      const selection = selectionRef.current;
      if (!selection.enabled || !selection.start || selection.pointerDown || selection.moved) {
        return;
      }
      if (!event.latlng.equals(selection.start)) finishSelection(event.latlng);
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
    if (!layers || selecting || region.west >= region.east || region.south >= region.north) {
      return;
    }
    layers.clearLayers();
    layers.addLayer(
      L.rectangle(
        [
          [region.south, region.west],
          [region.north, region.east],
        ],
        { color: "#16b8a6", weight: 2, fillOpacity: 0.12 },
      ),
    );
  }, [region, selecting]);

  function toggleSelection() {
    const map = mapRef.current;
    if (!map) return;
    if (selecting) {
      selectionRef.current = emptySelection();
      previewRef.current?.remove();
      previewRef.current = null;
      map.dragging.enable();
      map.getContainer().classList.remove("drawing-region");
      setSelecting(false);
      return;
    }
    selectionRef.current = { ...emptySelection(), enabled: true };
    map.dragging.disable();
    map.getContainer().classList.add("drawing-region");
    setSelecting(true);
  }

  return (
    <section className="map-panel" aria-label="Query region map">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Query domain</p>
          <h2>Select a region</h2>
        </div>
        <div className="map-actions">
          <span className="map-hint">
            {selecting ? "Drag, or click two opposite corners" : "Draw or edit the selected region"}
          </span>
          <button
            className={selecting ? "secondary-button active" : "secondary-button"}
            type="button"
            onClick={toggleSelection}
          >
            {selecting ? "Cancel drawing" : "Draw region"}
          </button>
        </div>
      </div>
      <div className="map" ref={elementRef} />
    </section>
  );
}
