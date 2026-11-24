import React, { useState, useEffect } from 'react';
import { RotateCcw, CheckCircle2, Cpu, Bot } from 'lucide-react';
import api from '../api/client';
import { useAuthStore } from '../store/useAuthStore';

export const Settings: React.FC = () => {
  const { updateUserBalance } = useAuthStore();
  const [replayEnabled, setReplayEnabled] = useState(false);
  const [resetConfirm, setResetConfirm] = useState(false);
  const [resetAmount, setResetAmount] = useState('100000');
  const [resetLoading, setResetLoading] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // LLM config
  const [llmBase, setLlmBase] = useState('http://localhost:11434/v1');
  const [llmKey, setLlmKey] = useState('ollama');
  const [llmModel, setLlmModel] = useState('llama3.1');
  const [llmStatus, setLlmStatus] = useState<string | null>(null);
  const [llmSaving, setLlmSaving] = useState(false);

  // AI auto-trader config
  const [aiEnabled, setAiEnabled] = useState(false);
  const [aiWatchlist, setAiWatchlist] = useState('RELIANCE,TCS,INFY');
  const [aiInterval, setAiInterval] = useState(15);
  const [aiMaxTrades, setAiMaxTrades] = useState(5);
  const [aiCooldown, setAiCooldown] = useState(30);
  const [aiMinConf, setAiMinConf] = useState(0.6);
  const [aiDryRun, setAiDryRun] = useState(true);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await api.get('/market/status');
        setReplayEnabled(res.data.replay_mode);
      } catch (e) {
        console.error(e);
      }
    };
    const loadConfig = async () => {
      try {
        const res = await api.get('/ai/config');
        const l = res.data.llm || {};
        setLlmBase(l.base_url || llmBase);
        setLlmKey(l.api_key || llmKey);
        setLlmModel(l.model || llmModel);
        const a = res.data.ai || {};
        setAiEnabled(!!a.enabled);
        setAiWatchlist((a.watchlist || []).join(',') || aiWatchlist);
        setAiInterval(a.interval_minutes || 15);
        setAiMaxTrades(a.max_trades_per_day || 5);
        setAiCooldown(a.cooldown_minutes || 30);
        setAiMinConf(a.min_confidence || 0.6);
        setAiDryRun(!!a.dry_run);
      } catch (e) {
        console.error(e);
      }
    };
    checkStatus();
    loadConfig();
  }, []);

  const toggleReplay = async () => {
    try {
      if (replayEnabled) {
        await api.post('/admin/replay/stop');
        setReplayEnabled(false);
        setMsg('Replay mode disabled. Market hours check is now active.');
      } else {
        await api.post('/admin/replay/start');
        setReplayEnabled(true);
        setMsg('Replay mode active! You can trade and test orders anytime outside market hours.');
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveLlm = async () => {
    setLlmSaving(true);
    setLlmStatus(null);
    try {
      await api.post('/ai/config', { llm: { base_url: llmBase, api_key: llmKey, model: llmModel } });
      setLlmStatus('LLM settings saved.');
    } catch (e: any) {
      setLlmStatus('Save failed: ' + (e?.response?.data?.detail || e?.message));
    } finally {
      setLlmSaving(false);
    }
  };

  const handleTestLlm = async () => {
    setLlmStatus('Testing...');
    try {
      const res = await api.post('/ai/test-connection', { base_url: llmBase, api_key: llmKey, model: llmModel });
      if (res.data.reachable) {
        setLlmStatus(`Connected. ${ (res.data.models || []).length } models available.`);
      } else {
        setLlmStatus('Not reachable: ' + (res.data.error || 'unknown error'));
      }
    } catch (e: any) {
      setLlmStatus('Test failed: ' + (e?.response?.data?.detail || e?.message));
    }
  };

  const handleSaveAi = async () => {
    try {
      await api.post('/ai/config', {
        ai: {
          enabled: aiEnabled,
          watchlist: aiWatchlist.split(',').map(s => s.trim()).filter(Boolean),
          interval_minutes: Number(aiInterval),
          max_trades_per_day: Number(aiMaxTrades),
          cooldown_minutes: Number(aiCooldown),
          min_confidence: Number(aiMinConf),
          dry_run: aiDryRun,
        },
      });
      setMsg('AI auto-trader settings saved.');
    } catch (e) {
      console.error(e);
    }
  };

  const handleResetAccount = async () => {
    const amount = Number(resetAmount);
    if (!Number.isFinite(amount) || amount < 1) {
      setResetError('Enter a valid amount of at least ₹1.');
      return;
    }
    setResetError(null);
    setResetLoading(true);
    try {
      const res = await api.post('/account/reset', { amount });
      const newBalance = Number(res.data.new_balance);
      updateUserBalance(newBalance, res.data.starting_balance ?? newBalance);
      setResetConfirm(false);
      setMsg(
        `Account reset complete! Virtual capital set to ₹${newBalance.toLocaleString('en-IN')}.`
      );
    } catch (e: any) {
      setResetError(
        'Reset failed: ' + (e?.response?.data?.detail || e?.message || 'unknown error')
      );
    } finally {
      setResetLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-black text-slate-900">Settings & Simulator Control</h1>
        <p className="text-xs text-slate-400">Manage virtual balance, market simulation replay mode, and user profile</p>
      </div>

      {msg && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-2xl text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
          <span>{msg}</span>
        </div>
      )}

      {/* Simulator Replay Mode */}
      <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm flex items-center justify-between gap-6">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-bold text-sm text-slate-900">Market Replay Mode</h3>
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                replayEnabled ? 'bg-indigo-50 text-indigo-700' : 'bg-slate-100 text-slate-500'
              }`}
            >
              {replayEnabled ? 'ACTIVE' : 'OFF'}
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1 max-w-md">
            When enabled, the market is simulated as open 24/7. This allows you to test market, limit, stop-loss orders and square-offs on weekends and evenings.
          </p>
        </div>
        <button
          onClick={toggleReplay}
          className={`px-5 py-2.5 rounded-2xl text-xs font-bold transition-all shadow-sm ${
            replayEnabled
              ? 'bg-rose-50 text-rose-600 border border-rose-200 hover:bg-rose-100'
              : 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-indigo-100'
          }`}
        >
          {replayEnabled ? 'Disable Replay' : 'Enable Replay'}
        </button>
      </div>

      {/* Account Reset */}
      <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h3 className="font-bold text-sm text-slate-900 flex items-center gap-2">
              <RotateCcw className="w-4 h-4 text-rose-500" /> Reset Virtual Account
            </h3>
            <p className="text-xs text-slate-400 mt-1 max-w-md">
              Resets your portfolio, holdings, positions, and trades back to zero, then funds your wallet with the amount you choose (default ₹1,00,000).
            </p>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center gap-2 shrink-0">
            <label
              className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-semibold transition-colors ${
                resetConfirm
                  ? 'border-rose-300 bg-white text-slate-900'
                  : 'border-slate-200 bg-slate-50 text-slate-500'
              }`}
            >
              <span className="text-slate-400">₹</span>
              <input
                type="number"
                min={1}
                step={1000}
                inputMode="numeric"
                aria-label="Reset amount in rupees"
                value={resetAmount}
                onChange={(e) => {
                  setResetAmount(e.target.value);
                  setResetError(null);
                }}
                disabled={!resetConfirm || resetLoading}
                className="w-28 bg-transparent outline-none disabled:text-slate-400"
              />
            </label>

            {resetConfirm ? (
              <>
                <button
                  onClick={handleResetAccount}
                  disabled={resetLoading}
                  className="px-4 py-2 rounded-xl bg-rose-600 text-white text-xs font-bold shadow-md hover:bg-rose-700 disabled:opacity-60"
                >
                  {resetLoading ? 'Applying...' : 'Apply'}
                </button>
                <button
                  onClick={() => {
                    setResetConfirm(false);
                    setResetError(null);
                  }}
                  disabled={resetLoading}
                  className="px-3 py-2 rounded-xl bg-slate-100 text-slate-600 text-xs font-semibold disabled:opacity-60"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={() => {
                  setResetConfirm(true);
                  setResetError(null);
                }}
                className="px-5 py-2.5 rounded-2xl border border-rose-200 text-rose-600 hover:bg-rose-50 text-xs font-bold transition-all"
              >
                Reset Funds
              </button>
            )}
          </div>
        </div>
        {resetError && (
          <p className="text-[11px] font-semibold text-rose-600 mt-3">{resetError}</p>
        )}
      </div>

      {/* LLM Configuration */}
      <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-4">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-indigo-600" />
          <h3 className="font-bold text-sm text-slate-900">Local AI (LLM) Configuration</h3>
        </div>
        <p className="text-xs text-slate-400">Point to any OpenAI-compatible endpoint (Ollama, LM Studio, etc.). Stored locally.</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" placeholder="Base URL" value={llmBase} onChange={e => setLlmBase(e.target.value)} />
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" placeholder="API Key" value={llmKey} autoComplete="off" onChange={e => setLlmKey(e.target.value)} />
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" placeholder="Model" value={llmModel} onChange={e => setLlmModel(e.target.value)} />
        </div>
        <p className="text-[10px] text-slate-400">
          Saved API keys are masked. Leave the field unchanged to keep the current key.
        </p>
        <div className="flex items-center gap-2">
          <button onClick={handleSaveLlm} disabled={llmSaving} className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-bold hover:bg-indigo-700 disabled:opacity-50">
            {llmSaving ? 'Saving...' : 'Save LLM Settings'}
          </button>
          <button onClick={handleTestLlm} className="px-4 py-2 rounded-xl border border-slate-200 text-slate-700 text-xs font-bold hover:bg-slate-50">
            Test Connection
          </button>
          {llmStatus && <span className="text-xs text-slate-500">{llmStatus}</span>}
        </div>
      </div>

      {/* AI Auto-Trader */}
      <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-4">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-emerald-600" />
          <h3 className="font-bold text-sm text-slate-900">AI Auto-Trader</h3>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${aiEnabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
            {aiEnabled ? 'ENABLED' : 'DISABLED'}
          </span>
        </div>
        <p className="text-xs text-slate-400">Runs on a watchlist during market hours (or replay). Guardrails: daily trade cap, cooldown, min confidence, dry-run.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={aiEnabled} onChange={e => setAiEnabled(e.target.checked)} />
            Enabled
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={aiDryRun} onChange={e => setAiDryRun(e.target.checked)} />
            Dry run (no real orders)
          </label>
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" placeholder="Watchlist (comma)" value={aiWatchlist} onChange={e => setAiWatchlist(e.target.value)} />
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" placeholder="Interval (min)" value={aiInterval} onChange={e => setAiInterval(Number(e.target.value))} />
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" placeholder="Max trades/day" value={aiMaxTrades} onChange={e => setAiMaxTrades(Number(e.target.value))} />
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" placeholder="Cooldown (min)" value={aiCooldown} onChange={e => setAiCooldown(Number(e.target.value))} />
          <input className="px-3 py-2 rounded-xl border border-slate-200 text-xs" type="number" step="0.1" placeholder="Min confidence" value={aiMinConf} onChange={e => setAiMinConf(Number(e.target.value))} />
        </div>
        <button onClick={handleSaveAi} className="px-4 py-2 rounded-xl bg-emerald-600 text-white text-xs font-bold hover:bg-emerald-700">
          Save Auto-Trader Settings
        </button>
      </div>

      {/* Architecture Specs */}
      <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-3">
        <h3 className="font-bold text-sm text-slate-900">Simulator System Specs</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          <div className="p-3 bg-slate-50 rounded-xl">
            <span className="text-slate-400">Starting Cash:</span>
            <span className="font-bold text-slate-800 ml-2">₹10,00,000 (10 Lakhs)</span>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl">
            <span className="text-slate-400">Intraday (MIS) Margin:</span>
            <span className="font-bold text-slate-800 ml-2">20% (5x Leverage)</span>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl">
            <span className="text-slate-400">NSE Market Hours:</span>
            <span className="font-bold text-slate-800 ml-2">09:15 AM - 03:30 PM IST</span>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl">
            <span className="text-slate-400">MIS Auto Square-Off:</span>
            <span className="font-bold text-slate-800 ml-2">03:15 PM IST</span>
          </div>
        </div>
      </div>
    </div>
  );
};
