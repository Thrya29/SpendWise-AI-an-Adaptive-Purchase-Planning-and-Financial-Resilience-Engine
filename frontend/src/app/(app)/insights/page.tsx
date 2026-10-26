"use client";

import { useState } from "react";

import { DepositCard, SafeToLockCard } from "@/components/insights/deposits";
import { FundsCard } from "@/components/insights/funds";
import { GoldCard } from "@/components/insights/gold";
import { SimulatorCard } from "@/components/insights/simulator";
import { Alert, PageHeader } from "@/components/ui";
import { api, type Schemas } from "@/lib/api/client";
import { useUser } from "@/lib/auth";
import { useResource } from "@/lib/use-resource";

type Fund = Schemas["FundOut"];

export default function InsightsPage() {
  const user = useUser();
  const [preset, setPreset] = useState<{ amountMinor: number; months: number } | null>(null);
  const [fundCode, setFundCode] = useState<number | null>(null);
  const watchlist = useResource<Fund[]>("watchlist", (signal) =>
    api<Fund[]>("/funds/watchlist", { signal }),
  );

  return (
    <>
      <PageHeader
        title="Savings & investing"
        description="Understand your options with your own numbers. Education, not advice."
      />
      <div className="mb-6">
        <Alert tone="brand" title="Not investment advice">
          SpendWise explains and simulates; it never tells you which fund or stock to buy. For
          personal advice, consult a SEBI-registered investment adviser.
        </Alert>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <SafeToLockCard onUse={(amountMinor, months) => setPreset({ amountMinor, months })} />
        <DepositCard currency={user.base_currency} preset={preset} />
        <SimulatorCard
          currency={user.base_currency}
          funds={watchlist.data ?? []}
          fundCode={fundCode}
          onFundCode={setFundCode}
        />
        <FundsCard watchlist={watchlist} onSimulate={setFundCode} />
        <div className="lg:col-span-2">
          <GoldCard currency={user.base_currency} />
        </div>
      </div>
    </>
  );
}
