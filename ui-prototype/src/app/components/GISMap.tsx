import { useRef, useEffect, useCallback, useState } from "react";
import { FarmerRecord } from "./mockData";
import { Layers, ZoomIn, ZoomOut, RotateCcw, Navigation } from "lucide-react";

interface LayerState {
  typhoonPath: boolean;
  farmPolygons: boolean;
  windRadius: boolean;
  municipalityLabels: boolean;
}

interface GISMapProps {
  farmers: FarmerRecord[];
  selectedFarmId: string | null;
  onSelectFarm: (id: string | null) => void;
  darkMode: boolean;
  filterMunicipality?: string;
}

const PROVINCE_OUTLINE: [number, number][] = [
  [60,90],[130,45],[250,35],[400,45],[520,60],[650,95],
  [740,140],[780,210],[770,300],[730,390],[670,460],
  [580,505],[460,525],[340,515],[220,490],[130,445],
  [75,380],[55,280],[55,180],[60,90],
];

const MUNICIPALITY_LABELS = [
  { name:"Naga City",  x:380, y:232 },
  { name:"Pili",       x:490, y:290 },
  { name:"Libmanan",   x:280, y:370 },
  { name:"Sipocot",    x:200, y:428 },
  { name:"Goa",        x:570, y:400 },
  { name:"Lagonoy",    x:625, y:460 },
];

const TYPHOON_TRACK: [number, number][] = [
  [790,200],[700,218],[590,238],[480,262],[370,288],[260,318],[150,355],[50,388],
];

function pointInPolygon(pt: [number, number], poly: [number, number][]): boolean {
  const [px, py] = pt;
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

const GROWTH_COLORS: Record<string, string> = {
  Seedling:     "#86efac",
  Vegetative:   "#22c55e",
  Reproductive: "#eab308",
  Ripening:     "#f59e0b",
};

const SIGNAL_DOT_COLORS: Record<number, string> = {
  1: "#22c55e",
  2: "#f59e0b",
  3: "#ef4444",
};

function polyCenter(coords: [number, number][]): [number, number] {
  const x = coords.reduce((s, [cx]) => s + cx, 0) / coords.length;
  const y = coords.reduce((s, [, cy]) => s + cy, 0) / coords.length;
  return [x, y];
}

export function GISMap({ farmers, selectedFarmId, onSelectFarm, darkMode, filterMunicipality }: GISMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [layers, setLayers] = useState<LayerState>({ typhoonPath:true, farmPolygons:true, windRadius:true, municipalityLabels:true });
  const [showLayerPanel, setShowLayerPanel] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [canvasW, setCanvasW] = useState(800);
  const [canvasH, setCanvasH] = useState(480);
  const [zoom, setZoom] = useState(1);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; farm: FarmerRecord } | null>(null);

  const visibleFarmers = filterMunicipality
    ? farmers.filter(f => f.municipality === filterMunicipality)
    : farmers;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const W = canvas.width;
    const H = canvas.height;

    ctx.clearRect(0, 0, W, H);

    // Ocean
    ctx.fillStyle = darkMode ? "#0a1628" : "#9fc8e0";
    ctx.fillRect(0, 0, W, H);

    // Province fill
    ctx.beginPath();
    PROVINCE_OUTLINE.forEach(([x, y], i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y));
    ctx.closePath();
    ctx.fillStyle = darkMode ? "#192e19" : "#c8e0b4";
    ctx.fill();
    ctx.strokeStyle = darkMode ? "#4ade80" : "#2d7a2d";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Municipality dividers
    ctx.strokeStyle = darkMode ? "rgba(100,200,100,0.25)" : "rgba(30,100,30,0.35)";
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 5]);
    const dividers: [[number,number],[number,number]][] = [
      [[330,55],[330,515]], [[540,80],[540,510]], [[80,310],[710,310]],
      [[200,315],[200,495]], [[540,310],[680,510]],
    ];
    dividers.forEach(([a, b]) => { ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(b[0],b[1]); ctx.stroke(); });
    ctx.setLineDash([]);

    // Wind radius circles
    if (layers.windRadius) {
      const circles = [
        { x:590, y:238, r:90,  signal:3 },
        { x:480, y:262, r:110, signal:2 },
        { x:370, y:288, r:125, signal:1 },
      ];
      const fills   = ["rgba(254,240,138,0.08)","rgba(251,146,60,0.10)","rgba(239,68,68,0.12)"];
      const strokes = ["rgba(234,179,8,0.45)",   "rgba(249,115,22,0.55)","rgba(239,68,68,0.65)"];
      circles.forEach(({ x, y, r, signal }) => {
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle   = fills[signal-1];   ctx.fill();
        ctx.strokeStyle = strokes[signal-1]; ctx.lineWidth = 1.5;
        ctx.setLineDash([5,4]); ctx.stroke(); ctx.setLineDash([]);
      });
    }

    // Farm polygons
    if (layers.farmPolygons) {
      visibleFarmers.forEach(f => {
        if (!f.mapCoords?.length) return;
        const sel = f.farmId === selectedFarmId;
        const hov = f.farmId === hoveredId;

        ctx.beginPath();
        f.mapCoords.forEach(([x, y], i) => i === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y));
        ctx.closePath();

        if (!f.planted) {
          ctx.fillStyle = "rgba(150,150,150,0.4)"; ctx.fill();
          ctx.strokeStyle = "#888"; ctx.lineWidth = 1;
          ctx.setLineDash([3,3]); ctx.stroke(); ctx.setLineDash([]);
        } else {
          const base = GROWTH_COLORS[f.growthStage] ?? "#86efac";
          ctx.fillStyle = sel ? base : base + "cc"; ctx.fill();
          ctx.strokeStyle = sel ? "#ffffff" : hov ? "#ffffffaa" : "rgba(0,0,0,0.3)";
          ctx.lineWidth = sel ? 3 : hov ? 2 : 1;
          ctx.stroke();

          // signal dot
          const [cx, cy] = polyCenter(f.mapCoords);
          ctx.beginPath(); ctx.arc(cx, cy, 4.5, 0, Math.PI * 2);
          ctx.fillStyle = SIGNAL_DOT_COLORS[f.signalNo] ?? "#ccc"; ctx.fill();
          ctx.strokeStyle = "rgba(0,0,0,0.4)"; ctx.lineWidth = 0.8; ctx.stroke();
        }
      });
    }

    // Typhoon track
    if (layers.typhoonPath) {
      ctx.beginPath();
      TYPHOON_TRACK.forEach(([x, y], i) => i === 0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y));
      ctx.strokeStyle = "#ff5200"; ctx.lineWidth = 3;
      ctx.setLineDash([13,7]); ctx.stroke(); ctx.setLineDash([]);

      // Arrowheads along track
      for (let i = 1; i < TYPHOON_TRACK.length; i++) {
        const [x1,y1] = TYPHOON_TRACK[i-1];
        const [x2,y2] = TYPHOON_TRACK[i];
        const mx = (x1+x2)/2; const my = (y1+y2)/2;
        const angle = Math.atan2(y2-y1, x2-x1);
        ctx.save();
        ctx.translate(mx, my); ctx.rotate(angle);
        ctx.beginPath(); ctx.moveTo(0,0); ctx.lineTo(-8,-4); ctx.lineTo(-8,4); ctx.closePath();
        ctx.fillStyle = "#ff5200"; ctx.fill();
        ctx.restore();
      }

      // Typhoon eye symbol at current position
      const [ex, ey] = TYPHOON_TRACK[3];
      ctx.beginPath(); ctx.arc(ex, ey, 14, 0, Math.PI*2);
      ctx.fillStyle   = "rgba(255,82,0,0.18)"; ctx.fill();
      ctx.strokeStyle = "#ff5200"; ctx.lineWidth = 2.5; ctx.stroke();
      ctx.beginPath(); ctx.arc(ex, ey, 5, 0, Math.PI*2);
      ctx.fillStyle = "#ff5200"; ctx.fill();

      // Typhoon label
      ctx.font = "bold 11px sans-serif";
      ctx.fillStyle = "#ff5200";
      ctx.fillText("⚡ PEPITO", ex + 17, ey - 10);
      ctx.font = "10px sans-serif";
      ctx.fillText("Signal No. 3", ex + 17, ey + 4);
    }

    // Municipality labels
    if (layers.municipalityLabels) {
      MUNICIPALITY_LABELS.forEach(({ name, x, y }) => {
        ctx.font = "bold 10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillStyle = darkMode ? "rgba(200,240,200,0.85)" : "rgba(15,55,15,0.85)";
        ctx.fillText(name.toUpperCase(), x, y);
        ctx.textAlign = "left";
      });
    }

    // Scale bar
    const sbX = 620, sbY = 452;
    ctx.fillStyle = darkMode ? "rgba(0,0,0,0.55)" : "rgba(255,255,255,0.75)";
    ctx.fillRect(sbX-4, sbY-2, 158, 22);
    ctx.strokeStyle = darkMode ? "#aaa" : "#666";
    ctx.lineWidth = 1; ctx.strokeRect(sbX-4, sbY-2, 158, 22);
    ctx.fillStyle = darkMode ? "#ddd" : "#333";
    ctx.font = "10px sans-serif";
    ctx.fillText("0────5────10 km", sbX, sbY+13);

    // Compass rose
    const cpx = 748, cpy = 432;
    ctx.font = "bold 11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillStyle = darkMode ? "#ccc" : "#333";
    ctx.fillText("N", cpx, cpy - 15);
    ctx.beginPath();
    ctx.moveTo(cpx, cpy-11); ctx.lineTo(cpx+6,cpy+6); ctx.lineTo(cpx,cpy+2); ctx.lineTo(cpx-6,cpy+6); ctx.closePath();
    ctx.fillStyle = "#ef4444"; ctx.fill();
    ctx.textAlign = "left";
  }, [visibleFarmers, selectedFarmId, hoveredId, layers, darkMode]);

  useEffect(() => { draw(); }, [draw, canvasW, canvasH, zoom]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setCanvasW(Math.floor(r.width));
      setCanvasH(Math.floor(r.height));
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const toCanvas = (e: React.MouseEvent<HTMLCanvasElement>): [number, number] => {
    const c = canvasRef.current!;
    const r = c.getBoundingClientRect();
    return [
      ((e.clientX - r.left) / r.width)  * 800,
      ((e.clientY - r.top)  / r.height) * 480,
    ];
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pt = toCanvas(e);
    let found: FarmerRecord | null = null;
    for (const f of visibleFarmers) {
      if (f.mapCoords && pointInPolygon(pt, f.mapCoords)) { found = f; break; }
    }
    setHoveredId(found?.farmId ?? null);
    if (canvasRef.current) canvasRef.current.style.cursor = found ? "pointer" : "default";
    if (found) {
      const r = canvasRef.current!.getBoundingClientRect();
      setTooltip({ x: e.clientX - r.left, y: e.clientY - r.top, farm: found });
    } else {
      setTooltip(null);
    }
  };

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pt = toCanvas(e);
    for (const f of visibleFarmers) {
      if (f.mapCoords && pointInPolygon(pt, f.mapCoords)) {
        onSelectFarm(f.farmId === selectedFarmId ? null : f.farmId);
        return;
      }
    }
    onSelectFarm(null);
  };

  const selectedFarm = selectedFarmId ? farmers.find(f => f.farmId === selectedFarmId) : null;

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden rounded-lg border border-border bg-card">
      <canvas
        ref={canvasRef}
        width={800}
        height={480}
        className="w-full h-full"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => { setHoveredId(null); setTooltip(null); }}
        onClick={handleClick}
      />

      {/* Map Controls */}
      <div className="absolute top-3 right-3 flex flex-col gap-1.5">
        <button
          onClick={() => setShowLayerPanel(v => !v)}
          className="w-8 h-8 rounded flex items-center justify-center shadow-md bg-card border border-border hover:bg-muted transition-colors"
          title="Toggle Layers"
        >
          <Layers size={14} />
        </button>
        <button
          onClick={() => setZoom(v => Math.min(v + 0.2, 2))}
          className="w-8 h-8 rounded flex items-center justify-center shadow-md bg-card border border-border hover:bg-muted transition-colors"
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={() => setZoom(v => Math.max(v - 0.2, 0.5))}
          className="w-8 h-8 rounded flex items-center justify-center shadow-md bg-card border border-border hover:bg-muted transition-colors"
        >
          <ZoomOut size={14} />
        </button>
        <button
          onClick={() => setZoom(1)}
          className="w-8 h-8 rounded flex items-center justify-center shadow-md bg-card border border-border hover:bg-muted transition-colors"
          title="Reset View"
        >
          <RotateCcw size={14} />
        </button>
      </div>

      {/* Layer Panel */}
      {showLayerPanel && (
        <div className="absolute top-3 right-12 bg-card border border-border rounded-lg shadow-xl p-3 min-w-[180px] z-10">
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">Map Layers</p>
          {(Object.entries(layers) as [keyof LayerState, boolean][]).map(([key, val]) => (
            <label key={key} className="flex items-center gap-2 py-1 cursor-pointer">
              <input
                type="checkbox"
                checked={val}
                onChange={() => setLayers(l => ({ ...l, [key]: !l[key] }))}
                className="accent-[#166534] w-3.5 h-3.5"
              />
              <span className="text-xs capitalize">{key.replace(/([A-Z])/g, ' $1').trim()}</span>
            </label>
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-3 left-3 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Growth Stage</p>
        {Object.entries(GROWTH_COLORS).map(([stage, color]) => (
          <div key={stage} className="flex items-center gap-1.5 mb-0.5">
            <span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: color }} />
            <span className="text-[10px]">{stage}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5 mt-1">
          <span className="w-3 h-3 rounded-sm inline-block bg-gray-400/60" />
          <span className="text-[10px]">Not Planted</span>
        </div>
      </div>

      {/* Signal Legend */}
      <div className="absolute bottom-3 left-36 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Signal No.</p>
        {([1,2,3] as const).map(s => (
          <div key={s} className="flex items-center gap-1.5 mb-0.5">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: SIGNAL_DOT_COLORS[s] }} />
            <span className="text-[10px]">Signal {s}</span>
          </div>
        ))}
      </div>

      {/* Hover Tooltip */}
      {tooltip && (
        <div
          className="absolute z-20 pointer-events-none bg-card border border-border rounded-lg shadow-xl p-2.5 min-w-[200px]"
          style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <Navigation size={10} className="text-[#166534]" />
            <span className="text-[11px] font-semibold">{tooltip.farm.farmId}</span>
          </div>
          <p className="text-[11px] font-medium">{tooltip.farm.insuredName}</p>
          <p className="text-[10px] text-muted-foreground">{tooltip.farm.barangay}, {tooltip.farm.municipality}</p>
          <div className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5">
            <span className="text-[10px] text-muted-foreground">Area:</span>
            <span className="text-[10px] font-medium">{tooltip.farm.areaHectare} ha</span>
            <span className="text-[10px] text-muted-foreground">Stage:</span>
            <span className="text-[10px] font-medium">{tooltip.farm.growthStage}</span>
            <span className="text-[10px] text-muted-foreground">Signal:</span>
            <span className="text-[10px] font-medium">No. {tooltip.farm.signalNo}</span>
          </div>
        </div>
      )}

      {/* Selected Farm Info Panel */}
      {selectedFarm && (
        <div className="absolute top-3 left-3 bg-card border-2 border-[#166534] rounded-lg shadow-xl p-3 min-w-[230px] z-10">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-bold text-[#166534] uppercase tracking-wide">Farm Details</span>
            <button onClick={() => onSelectFarm(null)} className="text-muted-foreground hover:text-foreground text-[10px]">✕</button>
          </div>
          <p className="text-[12px] font-semibold">{selectedFarm.insuredName}</p>
          <p className="text-[10px] text-muted-foreground mb-2">{selectedFarm.farmerId}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
            <span className="text-muted-foreground">Farm ID:</span><span className="font-medium">{selectedFarm.farmId}</span>
            <span className="text-muted-foreground">Municipality:</span><span className="font-medium">{selectedFarm.municipality}</span>
            <span className="text-muted-foreground">Barangay:</span><span className="font-medium">{selectedFarm.barangay}</span>
            <span className="text-muted-foreground">Area:</span><span className="font-medium">{selectedFarm.areaHectare} ha</span>
            <span className="text-muted-foreground">Growth Stage:</span>
            <span className="font-medium" style={{ color: GROWTH_COLORS[selectedFarm.growthStage] }}>{selectedFarm.growthStage}</span>
            <span className="text-muted-foreground">Planted:</span><span className="font-medium">{selectedFarm.planted ? "Yes" : "No"}</span>
            <span className="text-muted-foreground">Signal No.:</span>
            <span className="font-bold" style={{ color: SIGNAL_DOT_COLORS[selectedFarm.signalNo] }}>Signal {selectedFarm.signalNo}</span>
            <span className="text-muted-foreground">Exposure:</span><span className="font-medium">{selectedFarm.periodOfExposure}h</span>
            <span className="text-muted-foreground">Ind. Factor:</span><span className="font-medium text-amber-600">{selectedFarm.indemnityFactor}%</span>
            <span className="text-muted-foreground">Payment:</span><span className="font-bold text-[#166534]">₱{selectedFarm.indemnityPayment.toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}
