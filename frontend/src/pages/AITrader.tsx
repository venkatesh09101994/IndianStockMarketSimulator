import React, { useState, useEffect, useMemo } from 'react';
import api from '../api/client';

interface Decision {
  id: number;
  symbol: string;
  action: string;
  quantity: number;
  confidence: number;
  reasoning: string;
  model: string;
  executed: boolean;
  order_id?: number;
  created_at?: string;
  context?: any;
  memory_context?: string;
  graph_context?: string;
  memory_available?: boolean;
}

const Sparkline: React.FC<{ data: number[]; color: string }> = ({ data, color }) => {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 200;
  const h = 48;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline fill="none" stroke={color} strokeWidth="2" points={pts} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pts.split(' ').pop()?.split(',')[0]} cy={pts.split(' ').pop()?.split(',')[1]} r="3" fill={color} />
    </svg>
  );
};

// Module-level cache so AI Trader state survives tab switches
const AI_CACHE = {
  symbol: 'RELIANCE',
  status: null as { reachable: boolean; base_url: string; model: string; memory_available?: boolean } | null,
  latency: null as number | null,
  decision: null as any,
  history: [] as Decision[],
  msg: '',
  msgType: 'ok' as 'ok' | 'err',
};

export const AITrader: React.FC = () => {
  const [symbol, setSymbol] = useState(AI_CACHE.symbol);
  const [status, setStatus] = useState<{ reachable: boolean; base_url: string; model: string; memory_available?: boolean } | null>(AI_CACHE.status);
  const [latency, setLatency] = useState<number | null>(AI_CACHE.latency);
  const [decision, setDecision] = useState<any>(AI_CACHE.decision);
  const [history, setHistory] = useState<Decision[]>(AI_CACHE.history);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [msg, setMsg] = useState(AI_CACHE.msg);
  const [msgType, setMsgType] = useState<'ok' | 'err'>(AI_CACHE.msgType);

  const fetchStatus = async () => {
    const t0 = performance.now();
    try {
      const res = await api.get('/ai/status');
      setLatency(Math.round(performance.now() - t0));
      setStatus(res.data);
    } catch (e) {
      setStatus({ reachable: false, base_url: '', model: '' });
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await api.get('/ai/history');
      setHistory(res.data);
    } catch (e) {}
  };

  useEffect(() => {
    fetchStatus();
    fetchHistory();
  }, []);

  // persist to cache
  useEffect(() => { AI_CACHE.symbol = symbol; }, [symbol]);
  useEffect(() => { AI_CACHE.status = status; }, [status]);
  useEffect(() => { AI_CACHE.latency = latency; }, [latency]);
  useEffect(() => { AI_CACHE.decision = decision; }, [decision]);
  useEffect(() => { AI_CACHE.history = history; }, [history]);
  useEffect(() => { AI_CACHE.msg = msg; }, [msg]);
  useEffect(() => { AI_CACHE.msgType = msgType; }, [msgType]);

  const analyze = async () => {
    setLoading(true);
    setMsg('');
    setDecision(null);
    try {
      const res = await api.post('/ai/analyze', { symbol: symbol.toUpperCase() });
      setDecision(res.data);
      fetchHistory();
      setMsgType('ok');
      setMsg('Analysis complete');
    } catch (e: any) {
      setMsgType('err');
      setMsg(e?.response?.data?.detail || e?.response?.data?.error || e?.message || 'Analyze failed');
    } finally {
      setLoading(false);
    }
  };

  const execute = async () => {
    if (!decision?.id) return;
    setExecuting(true);
    setMsg('');
    try {
      const res = await api.post('/ai/execute', { decision_id: decision.id });
      setMsgType('ok');
      setMsg(res.data?.message || 'Executed');
      fetchHistory();
    } catch (e: any) {
      setMsgType('err');
      setMsg(e?.response?.data?.detail || e?.response?.data?.error || e?.message || 'Execute failed');
    } finally {
      setExecuting(false);
    }
  };

  const actionColor = (a: string) => a === 'BUY' ? 'text-emerald-600' : a === 'SELL' ? 'text-rose-600' : 'text-slate-500';
  const actionBg = (a: string) => a === 'BUY' ? 'from-emerald-50 to-emerald-50/30 border-emerald-200' : a === 'SELL' ? 'from-rose-50 to-rose-50/30 border-rose-200' : 'from-slate-50 to-slate-50/30 border-slate-200';

  const ctx = decision?.context;
  const sparkData = useMemo(() => (ctx?.history || []).map((h: any) => h.close), [ctx]);
  const cashNeeded = ctx && decision ? (decision.quantity * (ctx.price || 0)).toFixed(0) : '0';

  return (
    <div className="space-y-6">
      {/* Hero header */}
      <div className="relative overflow-hidden rounded-2xl bg-zinc-950 p-6 text-white shadow-xl border border-zinc-800">
        <div className="absolute right-0 top-0 -mt-10 -mr-10 w-72 h-72 rounded-full bg-zinc-800/40 blur-3xl pointer-events-none" />
        <div className="absolute left-0 bottom-0 -mb-10 -ml-10 w-64 h-64 rounded-full bg-emerald-900/20 blur-3xl pointer-events-none" />
        <div className="relative flex items-center justify-between flex-wrap gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-bold text-emerald-400 tracking-widest uppercase">Neural Trading Engine</span>
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-black tracking-tight">AI Trader</h1>
            <p className="text-xs sm:text-sm text-zinc-400 font-medium leading-relaxed mt-1">
              LLM-powered market analysis · paper execution · persistent memory · knowledge graph
            </p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="bg-zinc-900/60 border border-zinc-700 rounded-xl px-4 py-2 text-right">
              <div className="text-[10px] text-zinc-500 font-mono uppercase">Provider</div>
              <div className="text-white text-sm font-semibold">{status?.reachable ? status.model : '—'}</div>
            </div>
            <div className={`bg-zinc-900/60 border rounded-xl px-4 py-2 text-right ${status?.reachable ? 'border-emerald-500/40' : 'border-rose-500/40'}`}>
              <div className="text-[10px] text-zinc-500 font-mono uppercase">LLM</div>
              <div className={`text-sm font-semibold flex items-center gap-2 ${status?.reachable ? 'text-emerald-400' : 'text-rose-400'}`}>
                <span className={`w-2 h-2 rounded-full ${status?.reachable ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
                {status?.reachable ? 'Online' : 'Offline'}
                {latency !== null && <span className="text-zinc-500 text-xs font-normal">{latency}ms</span>}
              </div>
            </div>
            <div className={`bg-zinc-900/60 border rounded-xl px-4 py-2 text-right ${status?.memory_available ? 'border-cyan-500/40' : 'border-zinc-700'}`}>
              <div className="text-[10px] text-zinc-500 font-mono uppercase">Memory</div>
              <div className={`text-sm font-semibold ${status?.memory_available ? 'text-cyan-400' : 'text-zinc-500'}`}>
                {status?.memory_available ? 'Connected' : 'Offline'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {!status?.reachable && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-amber-800 text-sm flex items-start gap-3">
          <span className="text-xl">⚠</span>
          <div>
            <div className="font-semibold mb-1">LLM not reachable at <code className="bg-white px-1.5 py-0.5 rounded text-amber-900">{status?.base_url || '—'}</code></div>
            <div className="text-amber-700 text-xs">
              Set <code className="bg-white px-1 rounded">LLM_BASE_URL</code>, <code className="bg-white px-1 rounded">LLM_API_KEY</code>, <code className="bg-white px-1 rounded">LLM_MODEL</code> in a <code className="bg-white px-1 rounded">.env</code> next to the exe (or project root in dev).
              Local: run LM Studio / Ollama. Cloud: OpenAI / OpenRouter base URL + key.
            </div>
          </div>
        </div>
      )}

      {/* Analysis panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white rounded-2xl p-5 border border-slate-200/80 shadow-sm space-y-4">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Input</div>
            <div>
              <label className="text-slate-500 text-xs mb-1.5 block font-semibold">Symbol</label>
              <input
                value={symbol}
                onChange={e => setSymbol(e.target.value.toUpperCase())}
                className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5 text-slate-900 font-mono focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30"
                placeholder="RELIANCE"
              />
            </div>
            <button
              onClick={analyze}
              disabled={loading || !status?.reachable}
              className="w-full py-2.5 bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl font-bold transition-all shadow-md shadow-emerald-500/20"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Analyzing market…
                </span>
              ) : 'Run AI Analysis'}
            </button>
            {msg && (
              <div className={`text-xs px-3 py-2 rounded-lg ${msgType === 'ok' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-rose-50 text-rose-700 border border-rose-200'}`}>
                {msg}
              </div>
            )}
          </div>

          {ctx && (
            <div className="bg-white rounded-2xl p-5 border border-slate-200/80 shadow-sm space-y-3">
              <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Market Context</div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 text-xs">Price</span>
                <span className="text-slate-900 font-mono font-bold">₹{ctx.price?.toFixed(2)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 text-xs">Day Change</span>
                <span className={`font-mono font-bold ${ctx.day_change_pct >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                  {ctx.day_change_pct >= 0 ? '+' : ''}{ctx.day_change_pct?.toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 text-xs">Volume</span>
                <span className="text-slate-700 font-mono text-xs">{ctx.volume?.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 text-xs">52W Range</span>
                <span className="text-slate-700 font-mono text-xs">₹{ctx.week52_low?.toFixed(0)} – ₹{ctx.week52_high?.toFixed(0)}</span>
              </div>
              {sparkData.length > 1 && (
                <div className="pt-2">
                  <div className="text-[10px] text-slate-400 font-bold mb-1">10-SESSION TREND</div>
                  <Sparkline data={sparkData} color={sparkData[sparkData.length-1] >= sparkData[0] ? '#10b981' : '#f43f5e'} />
                </div>
              )}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 space-y-4">
          {decision && !decision.error ? (
            <div className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br ${actionBg(decision.action)} p-6 shadow-sm`}>
              <div className="flex items-center justify-between flex-wrap gap-4 mb-4">
                <div className="flex items-center gap-3">
                  <div className={`text-4xl font-black tracking-tight ${actionColor(decision.action)}`}>{decision.action}</div>
                  <div>
                    <div className="text-slate-900 font-bold">{decision.symbol}</div>
                    <div className="text-slate-500 text-xs">{ctx?.company}</div>
                  </div>
                </div>
                <div className="flex gap-4 flex-wrap">
                  <div className="text-right">
                    <div className="text-[10px] text-slate-400 font-bold uppercase">Quantity</div>
                    <div className="text-2xl font-black text-slate-900 font-mono">{decision.quantity}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-slate-400 font-bold uppercase">Confidence</div>
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-2 bg-slate-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${decision.action === 'BUY' ? 'bg-emerald-500' : decision.action === 'SELL' ? 'bg-rose-500' : 'bg-slate-400'}`}
                          style={{ width: `${(decision.confidence * 100).toFixed(0)}%` }}
                        />
                      </div>
                      <span className="text-slate-900 font-mono font-bold">{(decision.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-slate-400 font-bold uppercase">Est. Cost</div>
                    <div className="text-lg font-black text-slate-900 font-mono">₹{Number(cashNeeded).toLocaleString()}</div>
                  </div>
                </div>
              </div>
              <div className="bg-white/60 rounded-xl p-4 mb-4 border border-slate-200/50">
                <div className="text-[10px] text-slate-400 font-bold uppercase mb-1.5">AI Reasoning</div>
                <p className="text-slate-700 text-sm leading-relaxed">{decision.reasoning}</p>
              </div>
              {(decision.memory_context || decision.graph_context) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                  {decision.memory_context && (
                    <div className="bg-cyan-50 border border-cyan-200 rounded-xl p-3">
                      <div className="text-[10px] text-cyan-700 font-bold uppercase mb-1.5 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" /> AgentMemory Recall
                      </div>
                      <pre className="text-cyan-900 text-xs whitespace-pre-wrap font-mono">{decision.memory_context}</pre>
                    </div>
                  )}
                  {decision.graph_context && (
                    <div className="bg-violet-50 border border-violet-200 rounded-xl p-3">
                      <div className="text-[10px] text-violet-700 font-bold uppercase mb-1.5 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-violet-500" /> Knowledge Graph
                      </div>
                      <p className="text-violet-900 text-xs">{decision.graph_context}</p>
                    </div>
                  )}
                </div>
              )}
              <div className="flex items-center justify-between flex-wrap gap-3">
                <span className="text-xs text-slate-400 font-mono">Model: {decision.model}</span>
                {decision.action !== 'HOLD' && decision.quantity > 0 && (
                  <button
                    onClick={execute}
                    disabled={executing}
                    className={`px-5 py-2 rounded-xl font-bold text-sm transition-all shadow-md ${decision.action === 'BUY' ? 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-500/20' : 'bg-rose-600 hover:bg-rose-500 shadow-rose-500/20'} text-white disabled:opacity-40`}
                  >
                    {executing ? 'Executing…' : `Execute ${decision.action} · ${decision.quantity} shares`}
                  </button>
                )}
              </div>
            </div>
          ) : decision?.error ? (
            <div className="bg-rose-50 border border-rose-200 rounded-xl p-6 text-rose-700">
              <div className="font-bold mb-1">Analysis failed</div>
              <div className="text-sm">{decision.error}</div>
            </div>
          ) : (
            <div className="bg-white border border-slate-200/80 border-dashed rounded-2xl p-12 text-center">
              <div className="text-4xl mb-3">🧠</div>
              <div className="text-slate-500 text-sm">Enter a symbol and run AI analysis to get a trading decision.</div>
            </div>
          )}
        </div>
      </div>

      {/* History */}
      <div className="bg-white rounded-2xl p-5 border border-slate-200/80 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-slate-900 font-bold">Decision History</h2>
          <span className="text-xs text-slate-400 font-mono">{history.length} records</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-200 text-xs font-bold uppercase">
                <th className="text-left py-2.5">Time</th>
                <th className="text-left py-2.5">Symbol</th>
                <th className="text-left py-2.5">Action</th>
                <th className="text-right py-2.5">Qty</th>
                <th className="text-right py-2.5">Conf</th>
                <th className="text-left py-2.5">Reasoning</th>
                <th className="text-center py-2.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {history.map(h => (
                <tr key={h.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                  <td className="py-2.5 text-slate-400 text-xs font-mono">{h.created_at ? new Date(h.created_at).toLocaleTimeString() : ''}</td>
                  <td className="py-2.5 text-slate-900 font-bold">{h.symbol}</td>
                  <td className={`py-2.5 font-black font-mono ${actionColor(h.action)}`}>{h.action}</td>
                  <td className="py-2.5 text-right text-slate-700 font-mono">{h.quantity}</td>
                  <td className="py-2.5 text-right text-slate-700 font-mono">{(h.confidence * 100).toFixed(0)}%</td>
                  <td className="py-2.5 text-slate-500 text-xs max-w-md truncate" title={h.reasoning}>{h.reasoning}</td>
                  <td className="py-2.5 text-center">{h.executed ? <span className="text-emerald-600 font-bold">✓</span> : <span className="text-slate-300">—</span>}</td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-slate-400 text-sm">No decisions yet. Run an analysis above.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};