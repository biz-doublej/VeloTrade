"use server";

import { revalidatePath } from "next/cache";
import { supabaseVt } from "@/lib/supabase/server";

const VALID_TYPES = ["rsi", "ma_cross", "grid", "llm_signal"] as const;
const VALID_MODES = ["paper", "live", "dry_run"] as const;

type StrategyType = (typeof VALID_TYPES)[number];
type Mode = (typeof VALID_MODES)[number];

export async function createStrategyInstance(formData: FormData) {
  const name = String(formData.get("name") || "").trim();
  const strategyType = String(formData.get("strategy_type") || "");
  const accountId = String(formData.get("account_id") || "");
  const mode = String(formData.get("mode") || "paper");
  const symbolsRaw = String(formData.get("symbols") || "");
  const paramsJson = String(formData.get("params") || "{}");

  if (!name) return { error: "name required" };
  if (!VALID_TYPES.includes(strategyType as StrategyType)) {
    return { error: "invalid strategy_type" };
  }
  if (!VALID_MODES.includes(mode as Mode)) {
    return { error: "invalid mode" };
  }
  if (!accountId) return { error: "account_id required" };

  let params: Record<string, unknown>;
  try {
    params = JSON.parse(paramsJson);
  } catch {
    return { error: "params must be valid JSON" };
  }

  const symbols = symbolsRaw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const { error } = await supabaseVt.from("strategy_instances").insert({
    name,
    strategy_type: strategyType,
    account_id: accountId,
    symbols,
    params,
    mode,
    enabled: true,
  });

  if (error) return { error: error.message };
  revalidatePath("/dashboard/strategies");
  return { ok: true };
}

export async function toggleStrategyInstance(id: string, enabled: boolean) {
  const { error } = await supabaseVt
    .from("strategy_instances")
    .update({ enabled, updated_at: new Date().toISOString() })
    .eq("instance_id", id);
  if (error) return { error: error.message };
  revalidatePath("/dashboard/strategies");
  return { ok: true };
}

export async function deleteStrategyInstance(id: string) {
  const { error } = await supabaseVt
    .from("strategy_instances")
    .delete()
    .eq("instance_id", id);
  if (error) return { error: error.message };
  revalidatePath("/dashboard/strategies");
  return { ok: true };
}

export async function updateStrategyParams(id: string, paramsJson: string) {
  let params: Record<string, unknown>;
  try {
    params = JSON.parse(paramsJson);
  } catch {
    return { error: "params must be valid JSON" };
  }
  const { error } = await supabaseVt
    .from("strategy_instances")
    .update({ params, updated_at: new Date().toISOString() })
    .eq("instance_id", id);
  if (error) return { error: error.message };
  revalidatePath("/dashboard/strategies");
  return { ok: true };
}
