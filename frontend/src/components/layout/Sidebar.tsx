import React, { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  TrendingUp,
  Briefcase,
  ArrowLeftRight,
  Bookmark,
  Sparkles,
  Settings,
  Brain,
  Network,
} from 'lucide-react';
import { SMLogo } from '../common/SMLogo';

export const Sidebar: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [hovered, setHovered] = useState<string | null>(null);

  const navItems = [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/stocks', label: 'Stocks', icon: TrendingUp, matchPrefix: '/stock' },
    { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
    { to: '/orders', label: 'Orders', icon: ArrowLeftRight },
    { to: '/watchlist', label: 'Watchlist', icon: Bookmark },
    { to: '/insights', label: 'Insights', icon: Sparkles },
    { to: '/ai-trader', label: 'AI Trader', icon: Brain },
    { to: '/knowledge-graph', label: 'Knowledge Graph', icon: Network },
    { to: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <aside className="w-[74px] bg-white border-r border-slate-200/80 flex flex-col items-center py-6 select-none shrink-0 z-20">
      <div
        onClick={() => navigate('/')}
        className="w-11 h-11 mb-8 cursor-pointer hover:scale-105 transition-transform flex items-center justify-center drop-shadow-sm"
        title="Stock Market Simulator"
      >
        <SMLogo className="w-11 h-11 rounded-2xl" size={44} />
      </div>

      <nav className="flex-1 flex flex-col items-center gap-3 w-full px-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.matchPrefix
            ? location.pathname.startsWith(item.matchPrefix) || location.pathname === item.to
            : location.pathname === item.to;

          return (
            <NavLink
              key={item.to}
              to={item.to}
              title=""
              onMouseEnter={() => setHovered(item.to)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => setHovered(null)}
              className={`w-11 h-11 rounded-xl flex items-center justify-center transition-all group relative ${
                isActive
                  ? 'bg-zinc-900 text-white shadow-sm shadow-zinc-300 font-bold'
                  : 'text-slate-400 hover:text-slate-800 hover:bg-slate-100'
              }`}
            >
              <Icon className="w-5 h-5 transition-transform group-hover:scale-110" />
              {hovered === item.to && (
                <span className="absolute left-16 bg-zinc-900 text-white text-xs px-2.5 py-1 rounded-md whitespace-nowrap shadow-xl z-50">
                  {item.label}
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col items-center gap-2">
        <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" title="System Online" />
      </div>
    </aside>
  );
};
