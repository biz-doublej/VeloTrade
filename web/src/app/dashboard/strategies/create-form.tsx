"use client";

import { useState, useTransition } from "react";
import { createStrategyInstance } from "./actions";

interface AccountOption {
  account_id: string;
  exchange: string;
  account_type: string;
  label: string;
}

const PRESET_PARAMS = {
  rsi: '{"period": 21, "oversold": 30, "overbought": 75, "size_pct": 0.05}',
  ma_cross: '{"fast": 20, "slow": 50, "size_pct": 0.05}',
  grid: '{"levels": 10, "step_pct": 0.01, "size_pct": 0.02}',
  llm_signal: '{"provider": "openai", "model": "gpt-4o-mini", "max_size_pct": 0.05, "min_confidence": 0.65}',
} as const;

export function CreateStrategyForm({ accounts }: { accounts: AccountOption[] }) {
  const [pending, start] = useTransition();
  const [type, setType] = useState<keyof typeof PRESET_PARAMS>("rsi");
  const [paramsText, setParamsText] = useState<string>(PRESET_PARAMS.rsi);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <div className="mb-6">
        <button
          onClick={() => setOpen(true)}
          className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90"
        >
          + New Strategy
        </button>
      </div>
    );
  }

  return (
    <form
      action={(fd) =>
        start(async () => {
          setError(null);
          const r = await createStrategyInstance(fd);
          if (r?.error) setError(r.error);
          else setOpen(false);
        })
      }
      className="mb-6 grid grid-cols-2 gap-3 rounded-lg border border-border p-4"
    >
      <div>
        <label className="block text-xs text-muted-foreground mb-1">Name</label>
        <input
          name="name"
          required
          placeholder="e.g. RSI default"
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm"
        />
      </div>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">Strategy Type</label>
        <select
          name="strategy_type"
          value={type}
          onChange={(e) => {
            const v = e.target.value as keyof typeof PRESET_PARAMS;
            setType(v);
            setParamsText(PRESET_PARAMS[v]);
          }}
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm"
        >
          <option value="rsi">rsi</option>
          <option value="ma_cross">ma_cross</option>
          <option value="grid">grid</option>
          <option value="llm_signal">llm_signal</option>
        </select>
      </div>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">Account</label>
        <select
          name="account_id"
          required
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm"
        >
          <option value="">— select —</option>
          {accounts.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.exchange} / {a.account_type} / {a.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">Mode</label>
        <select
          name="mode"
          defaultValue="paper"
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm"
        >
          <option value="paper">paper</option>
          <option value="dry_run">dry_run</option>
          <option value="live">live</option>
        </select>
      </div>
      <div className="col-span-2">
        <label className="block text-xs text-muted-foreground mb-1">
          Symbols <span className="text-muted-foreground/60">(comma, leave empty to use watchlist)</span>
        </label>
        <input
          name="symbols"
          placeholder="AAPL, MSFT, NVDA"
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm font-mono"
        />
      </div>
      <div className="col-span-2">
        <label className="block text-xs text-muted-foreground mb-1">Params (JSON)</label>
        <textarea
          name="params"
          rows={2}
          value={paramsText}
          onChange={(e) => setParamsText(e.target.value)}
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm font-mono"
        />
      </div>
      <div className="col-span-2 flex items-center gap-3">
        <button
          disabled={pending}
          className="px-4 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50"
        >
          {pending ? "Creating…" : "Create"}
        </button>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
          className="px-4 py-1.5 rounded-md border border-border text-sm"
        >
          Cancel
        </button>
        {error ? <span className="text-xs text-rose-400">{error}</span> : null}
      </div>
    </form>
  );
}
