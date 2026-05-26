"use client";

import { useTransition, useState } from "react";
import { addWatchlistItem } from "./actions";

const EXCHANGE_DEFAULTS = {
  alpaca: "us_stock",
  binance: "crypto",
  upbit: "crypto",
} as const;

export function AddWatchlistForm() {
  const [pending, start] = useTransition();
  const [exchange, setExchange] = useState<keyof typeof EXCHANGE_DEFAULTS>("alpaca");
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      action={(fd) =>
        start(async () => {
          setError(null);
          fd.set("asset_class", EXCHANGE_DEFAULTS[exchange]);
          const r = await addWatchlistItem(fd);
          if (r?.error) setError(r.error);
          else {
            const input = document.getElementById("wl-symbol") as HTMLInputElement | null;
            if (input) input.value = "";
          }
        })
      }
      className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border border-border p-4"
    >
      <div>
        <label className="block text-xs text-muted-foreground mb-1">Exchange</label>
        <select
          name="exchange"
          value={exchange}
          onChange={(e) => setExchange(e.target.value as keyof typeof EXCHANGE_DEFAULTS)}
          className="bg-background border border-border rounded-md px-3 py-1.5 text-sm"
        >
          <option value="alpaca">alpaca (US stock)</option>
          <option value="binance">binance (crypto USDT)</option>
          <option value="upbit">upbit (KRW crypto)</option>
        </select>
      </div>
      <div className="flex-1 min-w-[180px]">
        <label className="block text-xs text-muted-foreground mb-1">
          Symbol{" "}
          <span className="text-muted-foreground/70">
            (e.g. AAPL, BTCUSDT, KRW-BTC)
          </span>
        </label>
        <input
          id="wl-symbol"
          name="symbol"
          autoComplete="off"
          placeholder={
            exchange === "alpaca"
              ? "AAPL"
              : exchange === "binance"
                ? "BTCUSDT"
                : "KRW-BTC"
          }
          className="w-full bg-background border border-border rounded-md px-3 py-1.5 text-sm"
        />
      </div>
      <button
        disabled={pending}
        className="px-4 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
      >
        {pending ? "Adding…" : "Add"}
      </button>
      {error ? <span className="text-xs text-rose-400">{error}</span> : null}
    </form>
  );
}
