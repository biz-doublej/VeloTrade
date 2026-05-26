"use server";

import { revalidatePath } from "next/cache";
import { supabaseVt } from "@/lib/supabase/server";

const VALID_EXCHANGES = ["alpaca", "binance", "upbit"] as const;
const VALID_ASSET_CLASSES = ["us_stock", "crypto"] as const;

type Exchange = (typeof VALID_EXCHANGES)[number];
type AssetClass = (typeof VALID_ASSET_CLASSES)[number];

export async function addWatchlistItem(formData: FormData) {
  const symbol = String(formData.get("symbol") || "").trim().toUpperCase();
  const exchange = String(formData.get("exchange") || "");
  const assetClass = String(formData.get("asset_class") || "");

  if (!symbol) return { error: "symbol required" };
  if (!VALID_EXCHANGES.includes(exchange as Exchange)) {
    return { error: "invalid exchange" };
  }
  if (!VALID_ASSET_CLASSES.includes(assetClass as AssetClass)) {
    return { error: "invalid asset_class" };
  }

  const { error } = await supabaseVt.from("watchlist_items").upsert(
    {
      symbol,
      exchange,
      asset_class: assetClass,
      enabled: true,
    },
    { onConflict: "exchange,symbol" },
  );

  if (error) return { error: error.message };
  revalidatePath("/dashboard/watchlist");
  return { ok: true };
}

export async function toggleWatchlistItem(itemId: string, enabled: boolean) {
  const { error } = await supabaseVt
    .from("watchlist_items")
    .update({ enabled })
    .eq("item_id", itemId);
  if (error) return { error: error.message };
  revalidatePath("/dashboard/watchlist");
  return { ok: true };
}

export async function removeWatchlistItem(itemId: string) {
  const { error } = await supabaseVt
    .from("watchlist_items")
    .delete()
    .eq("item_id", itemId);
  if (error) return { error: error.message };
  revalidatePath("/dashboard/watchlist");
  return { ok: true };
}
