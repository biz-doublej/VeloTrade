"use client";

import { useState, useTransition } from "react";
import { Badge } from "@/components/ui/badge";
import { TD, TR } from "@/components/ui/data-table";
import {
  deleteStrategyInstance,
  toggleStrategyInstance,
  updateStrategyParams,
} from "./actions";

export interface StrategyInstance {
  instance_id: string;
  name: string;
  strategy_type: string;
  params: Record<string, unknown>;
  account_id: string | null;
  symbols: string[];
  mode: string;
  enabled: boolean;
  updated_at: string;
}

export function StrategyRow({
  instance,
  exchangeLabel,
}: {
  instance: StrategyInstance;
  exchangeLabel?: string;
}) {
  const [pending, start] = useTransition();
  const [editing, setEditing] = useState(false);
  const [paramsText, setParamsText] = useState(
    JSON.stringify(instance.params, null, 0),
  );
  const [error, setError] = useState<string | null>(null);

  return (
    <TR>
      <TD className="font-medium">{instance.name}</TD>
      <TD>
        <Badge variant="info">{instance.strategy_type}</Badge>
      </TD>
      <TD className="text-xs">
        {exchangeLabel ?? "?"} · {instance.mode}
      </TD>
      <TD className="text-xs text-muted-foreground max-w-xs truncate" title={instance.symbols.join(", ")}>
        {instance.symbols.join(", ") || "—"}
      </TD>
      <TD className="font-mono text-xs">
        {editing ? (
          <div className="flex flex-col gap-1">
            <input
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
              className="bg-background border border-border rounded px-2 py-1 text-xs font-mono w-72"
            />
            <div className="flex gap-1">
              <button
                disabled={pending}
                onClick={() =>
                  start(async () => {
                    setError(null);
                    const r = await updateStrategyParams(
                      instance.instance_id,
                      paramsText,
                    );
                    if (r?.error) setError(r.error);
                    else setEditing(false);
                  })
                }
                className="px-2 py-0.5 rounded bg-primary text-primary-foreground text-xs"
              >
                Save
              </button>
              <button
                disabled={pending}
                onClick={() => {
                  setEditing(false);
                  setParamsText(JSON.stringify(instance.params, null, 0));
                  setError(null);
                }}
                className="px-2 py-0.5 rounded border border-border text-xs"
              >
                Cancel
              </button>
            </div>
            {error ? <span className="text-rose-400 text-xs">{error}</span> : null}
          </div>
        ) : (
          <button
            onClick={() => setEditing(true)}
            className="text-left hover:bg-muted px-1 rounded"
            title="Click to edit"
          >
            {paramsText || "{}"}
          </button>
        )}
      </TD>
      <TD>
        <Badge variant={instance.enabled ? "filled" : "muted"}>
          {instance.enabled ? "enabled" : "disabled"}
        </Badge>
      </TD>
      <TD align="right">
        <div className="flex justify-end gap-2">
          <button
            disabled={pending}
            onClick={() =>
              start(async () => {
                await toggleStrategyInstance(instance.instance_id, !instance.enabled);
              })
            }
            className="px-2 py-1 text-xs rounded-md border border-border hover:bg-muted disabled:opacity-50"
          >
            {instance.enabled ? "Disable" : "Enable"}
          </button>
          <button
            disabled={pending}
            onClick={() => {
              if (!confirm(`Delete "${instance.name}"?`)) return;
              start(async () => {
                await deleteStrategyInstance(instance.instance_id);
              });
            }}
            className="px-2 py-1 text-xs rounded-md border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </TD>
    </TR>
  );
}
