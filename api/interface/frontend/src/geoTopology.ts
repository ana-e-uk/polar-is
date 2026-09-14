type Position = [number, number];

type CoastlineGeometry = {
  type: "MultiLineString" | "LineString";
  arcs: number[][] | number[];
};

type CoastlineTopology = {
  transform: {
    scale: Position;
    translate: Position;
  };
  arcs: Position[][];
  objects: {
    coastlines: {
      geometries: CoastlineGeometry[];
    };
  };
};

export type CoastlineCoordinates = {
  longitudes: Array<number | null>;
  latitudes: Array<number | null>;
};

let coastlinePromise: Promise<CoastlineCoordinates> | null = null;

function decodeArc(topology: CoastlineTopology, reference: number): Position[] {
  const arc = topology.arcs[reference < 0 ? ~reference : reference];
  let x = 0;
  let y = 0;
  const decoded = arc.map(([deltaX, deltaY]) => {
    x += deltaX;
    y += deltaY;
    return [
      x * topology.transform.scale[0] + topology.transform.translate[0],
      y * topology.transform.scale[1] + topology.transform.translate[1],
    ] as Position;
  });
  return reference < 0 ? decoded.reverse() : decoded;
}

function decodeLine(topology: CoastlineTopology, references: number[]): Position[] {
  return references.flatMap((reference, index) => {
    const arc = decodeArc(topology, reference);
    return index === 0 ? arc : arc.slice(1);
  });
}

function decodeCoastlines(topology: CoastlineTopology): CoastlineCoordinates {
  const longitudes: Array<number | null> = [];
  const latitudes: Array<number | null> = [];
  topology.objects.coastlines.geometries.forEach((geometry) => {
    const lines = geometry.type === "LineString"
      ? [geometry.arcs as number[]]
      : geometry.arcs as number[][];
    lines.forEach((references) => {
      decodeLine(topology, references).forEach(([longitude, latitude]) => {
        longitudes.push(longitude);
        latitudes.push(latitude);
      });
      longitudes.push(null);
      latitudes.push(null);
    });
  });
  return { longitudes, latitudes };
}

export function loadCoastlines(): Promise<CoastlineCoordinates> {
  if (!coastlinePromise) {
    const url = `${import.meta.env.BASE_URL}topojson/world_110m.json`;
    coastlinePromise = fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`Unable to load map topology (${response.status})`);
        return response.json() as Promise<CoastlineTopology>;
      })
      .then(decodeCoastlines);
  }
  return coastlinePromise;
}
