import { DataTable, EmptyState, TH, THead } from "@/components/ui/data-table";
import { PageHeader } from "@/components/ui/page-header";
import { supabaseVt } from "@/lib/supabase/server";
import { CreateStrategyForm } from "./create-form";
import { StrategyRow, type StrategyInstance } from "./strategy-row";

export const revalidate = 0;

interface Account {
  account_id: string;
  exchange: string;
  account_type: string;
  label: string;
}

export default async function StrategiesPage() {
  const [{ data: instances }, { data: accounts }] = await Promise.all([
    supabaseVt
      .from("strategy_instances")
      .select("*")
      .order("created_at", { ascending: false }),
    supabaseVt
      .from("exchange_accounts")
      .select("account_id, exchange, account_type, label"),
  ]);

  const items = (instances || []) as StrategyInstance[];
  const accountList = (accounts || []) as Account[];
  const accountMap = new Map(accountList.map((a) => [a.account_id, a]));

  return (
    <>
      <PageHeader
        title="Strategies"
        description={`활성화된 전략 인스턴스 — 총 ${items.length}건 (활성 ${items.filter((i) => i.enabled).length})`}
      />

      <CreateStrategyForm accounts={accountList} />

      {items.length === 0 ? (
        <EmptyState message="전략 인스턴스 없음 — 위 'New Strategy' 로 추가" />
      ) : (
        <DataTable>
          <THead>
            <tr>
              <TH>Name</TH>
              <TH>Type</TH>
              <TH>Account</TH>
              <TH>Symbols</TH>
              <TH>Params</TH>
              <TH>Status</TH>
              <TH align="right">Actions</TH>
            </tr>
          </THead>
          <tbody>
            {items.map((inst) => {
              const acc = inst.account_id ? accountMap.get(inst.account_id) : null;
              return (
                <StrategyRow
                  key={inst.instance_id}
                  instance={inst}
                  exchangeLabel={acc ? `${acc.exchange}/${acc.label}` : undefined}
                />
              );
            })}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
