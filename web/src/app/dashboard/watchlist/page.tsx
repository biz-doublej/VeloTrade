import { DataTable, EmptyState, TH, THead } from "@/components/ui/data-table";
import { PageHeader } from "@/components/ui/page-header";
import { supabaseVt } from "@/lib/supabase/server";
import { AddWatchlistForm } from "./add-form";
import { WatchlistRow, type WatchlistItem } from "./watchlist-row";

export const revalidate = 0;  // 항상 fresh — mutate 후 즉시 반영

export default async function WatchlistPage() {
  const { data, error } = await supabaseVt
    .from("watchlist_items")
    .select("*")
    .order("exchange", { ascending: true })
    .order("symbol", { ascending: true });

  const items = (data || []) as WatchlistItem[];

  return (
    <>
      <PageHeader
        title="Watchlist"
        description={`봇이 추적할 종목 — 총 ${items.length}건 (활성 ${items.filter((i) => i.enabled).length})`}
      />

      <AddWatchlistForm />

      {error ? (
        <EmptyState message={`error: ${error.message}`} />
      ) : items.length === 0 ? (
        <EmptyState message="워치리스트 비어있음 — 위 폼으로 종목 추가" />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Exchange</TH>
              <TH>Symbol</TH>
              <TH>Asset Class</TH>
              <TH>Status</TH>
              <TH align="right">Actions</TH>
            </tr>
          </THead>
          <tbody>
            {items.map((item) => (
              <WatchlistRow key={item.item_id} item={item} />
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
