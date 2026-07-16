import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Scale } from "lucide-react";
import { useFinancialYear } from "@/AppContext";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loading } from "@/components/Loading";
import { Input } from "@/components/ui/input";

type Regime = {
  regime: string;
  financial_year: string;
  gross_taxable_income: number;
  standard_deduction: number;
  chapter_vi_a_deductions: number;
  net_taxable_income: number;
  slab_tax: number;
  special_rate_tax: number;
  rebate: number;
  surcharge: number;
  cess: number;
  total_tax: number;
  tds_credit: number;
  advance_tax: number;
  net_payable: number;
  refund_estimate: number;
  warnings: string[];
};
type Comparison = { old: Regime; new: Regime; recommended: "old" | "new"; estimated_savings: number };

export function TaxSummaryPage() {
  const { financialYear } = useFinancialYear();
  const [planningIncome, setPlanningIncome] = useState("");
  const [planningRate, setPlanningRate] = useState(() => localStorage.getItem("itr-planning-rate") || "6");
  const query = useQuery({ queryKey: ["tax-compare", financialYear], queryFn: () => api<Comparison>(`/api/tax/compare?financial_year=${encodeURIComponent(financialYear)}`) });
  if (query.isLoading) return <Loading label="Comparing tax regimes" />;
  if (!query.data) return <p className="text-sm text-destructive">{(query.error as Error)?.message}</p>;
  const data = query.data;
  const customIncome = planningIncome === "" ? data.new.net_taxable_income : Math.max(0, Number(planningIncome) || 0);
  const customRate = Math.min(100, Math.max(0, Number(planningRate) || 0));
  const customTax = customIncome * customRate / 100;
  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div><h1 className="text-2xl font-bold tracking-tight">Tax summary</h1><p className="mt-1 text-sm text-muted-foreground">Old versus new regime estimate for {financialYear}.</p></div>
        <Badge className="w-fit border-primary/30 bg-primary/10 text-primary"><CheckCircle2 className="mr-1 h-3.5 w-3.5" /> {data.recommended.toUpperCase()} regime saves {money(data.estimated_savings)}</Badge>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <RegimeCard title="Old regime" data={data.old} recommended={data.recommended === "old"} />
        <RegimeCard title="New regime" data={data.new} recommended={data.recommended === "new"} />
      </div>
      <Card><CardHeader><CardTitle>Custom planning scenario</CardTitle><CardDescription>Compare a percentage-based reserve with the statutory slab calculation. This does not overwrite filing tax.</CardDescription></CardHeader><CardContent><div className="grid gap-4 sm:grid-cols-3"><label><span className="mb-1 block text-sm font-medium">Income total to test</span><Input type="number" min="0" value={planningIncome} placeholder={String(data.new.net_taxable_income)} onChange={(event) => setPlanningIncome(event.target.value)} /></label><label><span className="mb-1 block text-sm font-medium">Planning rate (%)</span><Input type="number" min="0" max="100" step="0.01" value={planningRate} onChange={(event) => { setPlanningRate(event.target.value); localStorage.setItem("itr-planning-rate", event.target.value); }} /></label><div className="rounded-lg border bg-muted/40 p-4"><p className="text-xs text-muted-foreground">Custom reserve</p><p className="mt-2 text-2xl font-bold">{money(customTax)}</p><p className="mt-1 text-xs text-muted-foreground">{customRate.toFixed(2)}% of {money(customIncome)}</p></div></div><p className="mt-4 text-xs text-amber-700 dark:text-amber-300">Planning only: Indian individual income tax is slab-based and may also include special-rate income, rebate, surcharge and cess. Do not use this custom figure as the filing amount without verifying the return.</p></CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Scale className="h-5 w-5" />Scope note</CardTitle></CardHeader><CardContent className="space-y-2 text-sm text-muted-foreground"><p>This is a preparation estimate. It does not file a return and does not replace professional review.</p><p>Special-rate capital gains, marginal relief, residency, surcharge caps and deduction eligibility require source evidence and may need manual confirmation.</p></CardContent></Card>
    </div>
  );
}

function RegimeCard({ title, data, recommended }: { title: string; data: Regime; recommended: boolean }) {
  const rows: [string, number][] = [
    ["Gross taxable income", data.gross_taxable_income], ["Standard deduction", -data.standard_deduction], ["Chapter VI-A deductions", -data.chapter_vi_a_deductions], ["Net taxable income", data.net_taxable_income], ["Slab tax", data.slab_tax], ["Special-rate tax", data.special_rate_tax], ["Rebate", -data.rebate], ["Surcharge", data.surcharge], ["Health & education cess", data.cess], ["Total tax", data.total_tax], ["TDS / advance tax", -(data.tds_credit + data.advance_tax)], ["Net payable", data.net_payable], ["Refund estimate", data.refund_estimate],
  ];
  return <Card className={recommended ? "border-primary/50 ring-1 ring-primary/20" : ""}><CardHeader className="flex-row items-start justify-between"><div><CardTitle>{title}</CardTitle><CardDescription>{data.financial_year}</CardDescription></div>{recommended && <Badge className="bg-primary text-primary-foreground">Recommended</Badge>}</CardHeader><CardContent><div className="divide-y rounded-lg border">{rows.map(([label, value], index) => <div key={label} className={`flex items-center justify-between p-3 text-sm ${index === 3 || index === 8 || index === 11 ? "font-semibold" : ""}`}><span className="text-muted-foreground">{label}</span><span>{money(value)}</span></div>)}</div>{data.warnings.length > 0 && <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300">{data.warnings.join(" ")}</div>}</CardContent></Card>;
}
