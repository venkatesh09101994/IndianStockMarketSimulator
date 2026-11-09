import React, { useState, useEffect, useRef, useCallback } from 'react';
import api from '../api/client';

interface GraphNode { id: string; label: string; sector: string; group: string; }
interface GraphEdge { source: string; target: string; relation: string; weight: number; }
interface Graph { nodes: GraphNode[]; edges: GraphEdge[]; communities: Record<string, string[]>; node_count: number; edge_count: number; }

// Module-level cache so the graph survives tab switches (component unmount/remount)
const KG_CACHE: {
  positions: Record<string, { x: number; y: number; vx: number; vy: number }>;
  selected: string | null;
  filterSector: string;
  search: string;
  graph: Graph | null;
  simulated: boolean;
} = {
  positions: {},
  selected: null,
  filterSector: 'all',
  search: '',
  graph: null,
  simulated: false,
};

const SECTOR_COLORS: Record<string, string> = {};
const PALETTE = ['#10b981','#3b82f6','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#eab308','#a855f7','#22c55e','#64748b'];
function sectorColor(s: string): string {
  if (!SECTOR_COLORS[s]) {
    const idx = Object.keys(SECTOR_COLORS).length % PALETTE.length;
    SECTOR_COLORS[s] = PALETTE[idx];
  }
  return SECTOR_COLORS[s];
}

export const KnowledgeGraph: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [graph, setGraph] = useState<Graph | null>(KG_CACHE.graph);
  const [loading, setLoading] = useState(!KG_CACHE.graph);
  const [selected, setSelected] = useState<string | null>(KG_CACHE.selected);
  const [hovered, setHovered] = useState<string | null>(null);
  const [filterSector, setFilterSector] = useState<string>(KG_CACHE.filterSector);
  const [search, setSearch] = useState<string>(KG_CACHE.search);

  // persist to cache
  useEffect(() => { KG_CACHE.selected = selected; }, [selected]);
  useEffect(() => { KG_CACHE.filterSector = filterSector; }, [filterSector]);
  useEffect(() => { KG_CACHE.search = search; }, [search]);
  useEffect(() => { if (graph) KG_CACHE.graph = graph; }, [graph]);
  const positionsRef = useRef<Record<string, { x: number; y: number; vx: number; vy: number }>>({ ...KG_CACHE.positions });
  const animRef = useRef<number>(0);

  useEffect(() => {
    // If cached, skip fetch/simulation init
    if (KG_CACHE.graph && KG_CACHE.simulated) {
      setGraph(KG_CACHE.graph);
      positionsRef.current = { ...KG_CACHE.positions };
      setLoading(false);
      return;
    }
    (async () => {
      setLoading(true);
      try {
        let g: Graph;
        try {
          const res = await api.get('/graph/full');
          g = res.data;
        } catch (e) {
          const res = await api.post('/graph/build');
          const res2 = await api.get('/graph/full');
          g = res2.data;
        }
        if (!g.nodes) {
          const res = await api.post('/graph/build');
          const res2 = await api.get('/graph/full');
          g = res2.data;
        }
        setGraph(g);
        KG_CACHE.graph = g;
        const pos: Record<string, { x: number; y: number; vx: number; vy: number }> = {};
        const canvas = canvasRef.current;
        const w = canvas ? canvas.width : 800;
        const h = canvas ? canvas.height : 600;
        g.nodes.forEach((n, i) => {
          const angle = (i / g.nodes.length) * Math.PI * 2;
          const r = Math.min(w, h) * 0.35;
          pos[n.id] = { x: w / 2 + Math.cos(angle) * r, y: h / 2 + Math.sin(angle) * r, vx: 0, vy: 0 };
        });
        positionsRef.current = pos;
        KG_CACHE.positions = { ...pos };
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const nodeById = useCallback((id: string) => graph?.nodes.find(n => n.id === id), [graph]);

  // force simulation
  useEffect(() => {
    if (!graph || !canvasRef.current) return;
    if (KG_CACHE.simulated && Object.keys(positionsRef.current).length > 0) {
      // already converged; just redraw once and keep rendering for hover/selection
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const pos = positionsRef.current;
      const w = canvas.width;
      const h = canvas.height;
      const draw = () => {
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, w, h);
        for (const e of graph.edges) {
          const a = pos[e.source];
          const b = pos[e.target];
          if (!a || !b) continue;
          const srcNode = graph.nodes.find(n => n.id === e.source);
          const tgtNode = graph.nodes.find(n => n.id === e.target);
          if (filterSector !== 'all') {
            if (srcNode?.sector !== filterSector && tgtNode?.sector !== filterSector) continue;
          }
          const highlighted = selected && (e.source === selected || e.target === selected);
          ctx.strokeStyle = highlighted ? 'rgba(16,185,129,0.9)' : 'rgba(100,116,139,0.12)';
          ctx.lineWidth = highlighted ? 2 : 0.5;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
        for (const n of graph.nodes) {
          const p = pos[n.id];
          if (!p) continue;
          if (filterSector !== 'all' && n.sector !== filterSector) ctx.globalAlpha = 0.15;
          else ctx.globalAlpha = 1;
          const isSel = n.id === selected;
          const isHov = n.id === hovered;
          const color = sectorColor(n.sector);
          ctx.beginPath();
          ctx.arc(p.x, p.y, isSel ? 9 : isHov ? 7 : 4.5, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
          if (isSel || isHov) {
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.fillStyle = '#e2e8f0';
            ctx.font = '11px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(n.id, p.x, p.y - 13);
          }
          ctx.globalAlpha = 1;
        }
      };
      draw();
      // keep a lightweight render loop for hover/selection without forces
      let running = true;
      const loop = () => {
        if (!running) return;
        draw();
        animRef.current = requestAnimationFrame(loop);
      };
      animRef.current = requestAnimationFrame(loop);
      return () => { running = false; cancelAnimationFrame(animRef.current); };
    }
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const pos = positionsRef.current;
    const nodes = graph.nodes;
    const edges = graph.edges;

    let running = true;
    let iterations = 0;
    const MAX_ITERS = 250;
    const step = () => {
      if (!running) return;
      const w = canvas.width;
      const h = canvas.height;
      if (iterations < MAX_ITERS) {
        // repulsion
        for (let i = 0; i < nodes.length; i++) {
          for (let j = i + 1; j < nodes.length; j++) {
            const a = pos[nodes[i].id];
            const b = pos[nodes[j].id];
            if (!a || !b) continue;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const force = 500 / (dist * dist);
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            a.vx -= fx; a.vy -= fy;
            b.vx += fx; b.vy += fy;
          }
        }
        // attraction along edges
        for (const e of edges) {
          const a = pos[e.source];
          const b = pos[e.target];
          if (!a || !b) continue;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (dist - 80) * 0.003;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx += fx; a.vy += fy;
          b.vx -= fx; b.vy -= fy;
        }
        // centering + damping
        for (const n of nodes) {
          const p = pos[n.id];
          if (!p) continue;
          p.vx += (w / 2 - p.x) * 0.002;
          p.vy += (h / 2 - p.y) * 0.002;
          p.vx *= 0.8;
          p.vy *= 0.8;
          p.x += p.vx;
          p.y += p.vy;
          p.x = Math.max(20, Math.min(w - 20, p.x));
          p.y = Math.max(20, Math.min(h - 20, p.y));
        }
        iterations++;
        if (iterations >= MAX_ITERS) {
          KG_CACHE.simulated = true;
          KG_CACHE.positions = { ...positionsRef.current };
        }
      }

      // draw
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, w, h);

      for (const e of edges) {
        const a = pos[e.source];
        const b = pos[e.target];
        if (!a || !b) continue;
        const srcNode = nodeById(e.source);
        const tgtNode = nodeById(e.target);
        if (filterSector !== 'all') {
          if (srcNode?.sector !== filterSector && tgtNode?.sector !== filterSector) continue;
        }
        if (search) {
          const q = search.toLowerCase();
          if (!e.source.toLowerCase().includes(q) && !e.target.toLowerCase().includes(q)) continue;
        }
        const highlighted = selected && (e.source === selected || e.target === selected);
        ctx.strokeStyle = highlighted ? 'rgba(16,185,129,0.9)' : 'rgba(100,116,139,0.12)';
        ctx.lineWidth = highlighted ? 2 : 0.5;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      for (const n of nodes) {
        const p = pos[n.id];
        if (!p) continue;
        if (filterSector !== 'all' && n.sector !== filterSector) {
          ctx.globalAlpha = 0.15;
        } else {
          ctx.globalAlpha = 1;
        }
        if (search && !n.id.toLowerCase().includes(search.toLowerCase()) && !n.label.toLowerCase().includes(search.toLowerCase())) {
          ctx.globalAlpha = 0.1;
        }
        const isSel = n.id === selected;
        const isHov = n.id === hovered;
        const color = sectorColor(n.sector);
        ctx.beginPath();
        ctx.arc(p.x, p.y, isSel ? 9 : isHov ? 7 : 4.5, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        if (isSel || isHov) {
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 2;
          ctx.stroke();
          ctx.fillStyle = '#e2e8f0';
          ctx.font = '11px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(n.id, p.x, p.y - 13);
        }
        ctx.globalAlpha = 1;
      }

      // keep animating (for hover/selection) but stop force after convergence
      animRef.current = requestAnimationFrame(step);
    };
    animRef.current = requestAnimationFrame(step);
    return () => { running = false; cancelAnimationFrame(animRef.current); };
  }, [graph, selected, hovered, filterSector, search, nodeById]);

  const canvasCoords = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
  };

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!graph || !canvasRef.current) return;
    const { x, y } = canvasCoords(e);
    const pos = positionsRef.current;
    let found: string | null = null;
    for (const n of graph.nodes) {
      const p = pos[n.id];
      if (!p) continue;
      const dx = p.x - x;
      const dy = p.y - y;
      if (dx * dx + dy * dy < 144) { found = n.id; break; }
    }
    setSelected(found);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!graph || !canvasRef.current) return;
    const { x, y } = canvasCoords(e);
    const pos = positionsRef.current;
    let found: string | null = null;
    for (const n of graph.nodes) {
      const p = pos[n.id];
      if (!p) continue;
      const dx = p.x - x;
      const dy = p.y - y;
      if (dx * dx + dy * dy < 144) { found = n.id; break; }
    }
    setHovered(found);
  };

  const sectors = graph ? Object.keys(graph.communities) : [];
  const selectedNode = selected ? nodeById(selected) : null;
  const selectedNeighbors = selected ? (graph ? graph.edges.filter(e => e.source === selected || e.target === selected).map(e => e.source === selected ? e.target : e.source) : []) : [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Knowledge Graph</h1>
          <p className="text-slate-400 text-sm">Stock relationship network · sector communities · price correlations</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search symbol…"
            className="bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500"
          />
          <select
            value={filterSector}
            onChange={e => setFilterSector(e.target.value)}
            className="bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500"
          >
            <option value="all">All sectors</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            onClick={async () => { setLoading(true); try { await api.post('/graph/build'); const r = await api.get('/graph/full'); setGraph(r.data); } catch(e){} finally { setLoading(false); } }}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg font-semibold"
          >
            Rebuild
          </button>
        </div>
      </div>

      {loading && (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-12 text-center text-slate-400">
          <div className="w-8 h-8 border-3 border-emerald-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          Loading graph…
        </div>
      )}

      {!loading && graph && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="lg:col-span-3 bg-slate-900/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <canvas
              ref={canvasRef}
              width={900}
              height={600}
              onClick={handleCanvasClick}
              onMouseMove={handleMouseMove}
              className="w-full h-auto cursor-pointer"
              style={{ maxHeight: '600px' }}
            />
          </div>
          <div className="space-y-4">
            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
              <div className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Stats</div>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between"><span className="text-slate-400">Nodes</span><span className="text-white font-mono">{graph.node_count}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Edges</span><span className="text-white font-mono">{graph.edge_count}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Communities</span><span className="text-white font-mono">{Object.keys(graph.communities).length}</span></div>
              </div>
            </div>
            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
              <div className="text-xs font-mono text-slate-500 uppercase tracking-wider mb-2">Legend</div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {Object.keys(graph.communities).map(s => (
                  <div key={s} className="flex items-center gap-2 text-xs">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: sectorColor(s) }} />
                    <span className="text-slate-300 truncate">{s}</span>
                  </div>
                ))}
              </div>
            </div>
            {selectedNode && (
              <div className="bg-slate-800/40 border border-emerald-500/30 rounded-xl p-4">
                <div className="text-xs font-mono text-emerald-400 uppercase tracking-wider mb-2">Selected</div>
                <div className="text-white font-bold">{selectedNode.id}</div>
                <div className="text-slate-400 text-xs mb-2">{selectedNode.label}</div>
                <div className="text-slate-500 text-xs mb-2">Sector: {selectedNode.sector}</div>
                <div className="text-[10px] text-slate-500 font-mono uppercase mb-1">Neighbors ({selectedNeighbors.length})</div>
                <div className="flex flex-wrap gap-1">
                  {selectedNeighbors.slice(0, 20).map(n => (
                    <span key={n} className="text-[10px] bg-slate-700/50 text-slate-300 px-1.5 py-0.5 rounded font-mono">{n}</span>
                  ))}
                </div>
              </div>
            )}
            {!selected && (
              <div className="bg-slate-800/40 border border-slate-700/50 border-dashed rounded-xl p-4 text-center text-slate-500 text-xs">
                Click a node to inspect its connections.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};