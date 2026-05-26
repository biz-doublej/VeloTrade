"use client";

import { useTransition } from "react";
import { Badge } from "@/components/ui/badge";
import { TD, TR } from "@/components/ui/data-table";
import { removeWatchlistItem, toggleWatchlistItem } from "./actions";

export interface WatchlistItem {
  item_id: string;
  symbol: string;
  exchange: string;
  asset_class: string;
  enabled: boolean;
  created_at: string;
}

export function WatchlistRow({ item }: { item: WatchlistItem }) {
  const [pending, start] = useTransition();

  return (
    <TR>
      <TD>
        <Badge variant="muted">{item.exchange}</Badge>
      </TD>
      <TD className="font-medium">{item.symbol}</TD>
      <TD className="text-xs text-muted-foreground">{item.asset_class}</TD>
      <TD>
        <Badge variant={item.enabled ? "filled" : "muted"}>
          {item.enabled ? "enabled" : "disabled"}
        </Badge>
      </TD>
      <TD align="right">
        <div className="flex justify-end gap-2">
          <button
            disabled={pending}
            onClick={() =>
              start(async () => {
                await toggleWatchlistItem(item.item_id, !item.enabled);
              })
            }
            className="px-2 py-1 text-xs rounded-md border border-border hover:bg-muted disabled:opacity-50"
          >
            {item.enabled ? "Disable" : "Enable"}
          </button>
          <button
            disabled={pending}
            onClick={() => {
              if (!confirm(`Remove ${item.symbol}?`)) return;
              start(async () => {
                await removeWatchlistItem(item.item_id);
              });
            }}
            className="px-2 py-1 text-xs rounded-md border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 disabled:opacity-50"
          >
            Remove
          </button>
        </div>
      </TD>
    </TR>
  );
}
