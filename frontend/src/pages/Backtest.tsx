import React, { useState } from 'react';
import api from '../api/client';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';

export const Backtest: React.FC = () => {
  const [symbol, setSymbol] = useState('RELIANCE');
  const [strategy, setStrategy] = useState('sma_crossover');
  const [fast, setFast] = useState(10);
  const [slow, setSlow] = useState(30);
  const [rsiBuy, setRsiBuy] = useState(30);
  const [rsiSell, setRsiSell] = useState(70);
  const [days, setDays] = useState(252);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const run = async () => {
    setLoading(true);
    setMsg('');
    setResult(null);
    try {
      const params = strategy === 'sma_crossover' ? { fast, slow } : strategy === 'rsi' ? { rsi_buy: rsiBuy, rsi_sell: rsiSell } : {};
      const res = await api.post('/backtest/run', { symbol: symbol.toUpperCase(), strategy, params, period_days: days });
      setResult(res.data);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || e?.message || 'Backtest failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-black text-slate-900">Backtesting Engine</h1>
        <p className="text-xs text-slate-400">Replay a strategy over stored daily candles and see performance metrics.</p>
      </div>

      <div className="bg-white rounded-3xl p-5 border border-slate-200/80 shadow-sm space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="text-[11px] font-bold text-slate-500 mb-1 block">Symbol</label>
            <input className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" placeholder="RELIANCE" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
          </div>
          <div>
            <label className="text-[11px] font-bold text-slate-500 mb-1 block">Strategy</label>
            <select className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              <option value="buy_hold">Buy &amp; Hold</option>
              <option value="sma_crossover">SMA Crossover</option>
              <option value="rsi">RSI</option>
            </select>
          </div>
          <div>
            <label className="text-[11px] font-bold text-slate-500 mb-1 block">Period (days)</label>
            <input className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" placeholder="252" value={days} onChange={(e) => setDays(Number(e.target.value))} />
          </div>
          <div className="flex items-end">
            <button onClick={run} disabled={loading} className="w-full px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-bold hover:bg-indigo-700 disabled:opacity-50">
              {loading ? 'Running...' : 'Run Backtest'}
            </button>
          </div>
        </div>

        {strategy === 'sma_crossover' && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-bold text-slate-500 mb-1 block">Fast SMA (days)</label>
              <input className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" value={fast} onChange={(e) => setFast(Number(e.target.value))} />
            </div>
            <div>
              <label className="text-[11px] font-bold text-slate-500 mb-1 block">Slow SMA (days)</label>
              <input className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" value={slow} onChange={(e) => setSlow(Number(e.target.value))} />
            </div>
          </div>
        )}
        {strategy === 'rsi' && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-bold text-slate-500 mb-1 block">RSI Buy Below</label>
              <input className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" value={rsiBuy} onChange={(e) => setRsiBuy(Number(e.target.value))} />
            </div>
            <div>
              <label className="text-[11px] font-bold text-slate-500 mb-1 block">RSI Sell Above</label>
              <input className="w-full px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" value={rsiSell} onChange={(e) => setRsiSell(Number(e.target.value))} />
            </div>
          </div>
        )}
        {msg && <p className="text-xs text-rose-600">{msg}</p>}
      </div>

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-xs">
            <div className="bg-white rounded-xl p-3 border border-slate-200"><div className="text-slate-400 text-[10px] font-bold uppercase">Total Return</div><div className="font-black">{result.total_return_pct}%</div></div>
            <div className="bg-white rounded-xl p-3 border border-slate-200"><div className="text-slate-400 text-[10px] font-bold uppercase">CAGR</div><div className="font-black">{result.cagr_pct}%</div></div>
            <div className="bg-white rounded-xl p-3 border border-slate-200"><div className="text-slate-400 text-[10px] font-bold uppercase">Sharpe</div><div className="font-black">{result.sharpe}</div></div>
            <div className="bg-white rounded-xl p-3 border border-slate-200"><div className="text-slate-400 text-[10px] font-bold uppercase">Max DD</div><div className="font-black">{result.max_drawdown_pct}%</div></div>
            <div className="bg-white rounded-xl p-3 border border-slate-200"><div className="text-slate-400 text-[10px] font-bold uppercase">Trades</div><div className="font-black">{result.trade_count}</div></div>
            <div className="bg-white rounded-xl p-3 border border-slate-200"><div className="text-slate-400 text-[10px] font-bold uppercase">Win Rate</div><div className="font-black">{result.win_rate_pct}%</div></div>
          </div>
          <div className="bg-white rounded-3xl p-5 border border-slate-200/80 shadow-sm h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={result.equity_curve}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="#10b981" dot={false} name="Equity" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white rounded-3xl p-5 border border-slate-200/80 shadow-sm">
            <h3 className="font-bold text-sm text-slate-900 mb-3">Trades</h3>
            <div className="overflow-x-auto max-h-64">
              <table className="w-full text-xs">
                <thead className="text-slate-400 font-bold uppercase">
                  <tr><th className="text-left py-2">Type</th><th className="text-left py-2">Date</th><th className="text-right py-2">Price</th><th className="text-right py-2">Qty</th><th className="text-right py-2">P&L</th></tr>
                </thead>
                <tbody>
                  {result.trades.map((t: any, i: number) => (
                    <tr key={i} className="border-b border-slate-100">
                      <td className={`py-1.5 font-bold ${t.type === 'BUY' ? 'text-emerald-600' : 'text-rose-600'}`}>{t.type}</td>
                      <td className="py-1.5 text-slate-500">{t.date?.slice(0, 10)}</td>
                      <td className="py-1.5 text-right font-mono">{t.price}</td>
                      <td className="py-1.5 text-right font-mono">{t.qty}</td>
                      <td className="py-1.5 text-right font-mono">{t.pnl ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};