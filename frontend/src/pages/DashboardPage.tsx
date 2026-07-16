import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, BadgeIndianRupee, Files, Fingerprint, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loading } from "@/components/Loading";
import { useFinancialYear } from "@/AppContext";

type Dashboard = {
  financial_year: string;
  metrics: Record<string, number>;
  income_breakdown: { name: string; value: number }[];
  category_breakdown: { name: string; value: number }[];
  monthly_flow: { month: string; credits: number; debits: number }[];
  quality: { review_count: number; duplicate_count: number; self_transfer_count: number; document_count: number; unresolved_credit_count: number };
  readiness: { status: "ready" | "incomplete"; tax_ready: boolean; unresolved_credit_count: number; unresolved_credit_amount: number; authoritative_evidence_count: number; warnings: string[] };
  tax_comparison: { recommended: string; estimated_savings: number; old: { total_tax: number }; new: { total_tax: number } };
};

const metricLabels: Record<string, string> = {
  gross_credits: "Gross Credits",
  taxable_income: "Taxable Income",
  exempt_income: "Exempt Income",
  interest_income: "Interest Income",
  dividend_income: "Dividend Income",
  capital_gains: "Capital Gains",
  business_income: "Business Income",
  salary_income: "Salary Income",
  rental_income: "Rental Income",
  agricultural_income: "Agricultural Income",
  other_sources: "Other Sources",
  total_deductions: "Total Deductions",
  net_taxable_income: "Net Taxable Income",
  estimated_tax: "Estimated Tax",
  refund_estimate: "Refund Estimate",
};

export function DashboardPage() {
  const { financialYear } = useFinancialYear();
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<{ name: string }>("/api/profile") });
  const query = useQuery({
    queryKey: ["dashboard", financialYear],
    queryFn: () => api<Dashboard>(`/api/dashboard?financial_year=${encodeURIComponent(financialYear)}`),
    refetchInterval: 20_000,
  });

  if (query.isLoading) return <Loading label="Calculating income summary" />;
  if (query.isError || !query.data) return <ErrorState message={(query.error as Error)?.message} />;
  const data = query.data;
  const primaryMetrics = ["gross_credits", "taxable_income", "net_taxable_income", "estimated_tax", "refund_estimate"];
  const detailMetrics = Object.keys(metricLabels).filter((key) => !primaryMetrics.includes(key));

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{profile.data?.name && profile.data.name !== "Local User" ? `${profile.data.name}'s income dashboard` : "Income dashboard"}</h1>
          <p className="text-sm font-medium text-foreground">Taxpayer: {profile.data?.name || "Local User"}</p>
          <p className="mt-1 text-sm text-muted-foreground">Consolidated from every imported source for {financialYear}.</p>
        </div>
        {data.readiness.tax_ready ? <Badge className="w-fit border-primary/30 bg-primary/10 text-primary">Recommended: {data.tax_comparison.recommended.toUpperCase()} regime · save {money(data.tax_comparison.estimated_savings)}</Badge> : <Badge className="w-fit border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300">Provisional calculation</Badge>}
      </div>

      {!data.readiness.tax_ready && <Card className="border-amber-500/40 bg-amber-500/5"><CardContent className="flex gap-3 p-5"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" /><div><p className="font-semibold">Tax estimate is incomplete</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{data.readiness.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div></CardContent></Card>}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {primaryMetrics.map((key, index) => (
          <Card key={key} className={index === 2 ? "border-primary/40 bg-primary/5" : ""}>
            <CardContent className="p-5">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{metricLabels[key]}</p>
              <p className="mt-3 text-2xl font-bold">{money(data.metrics[key])}</p>
              <div className="mt-3 flex items-center gap-1 text-xs text-muted-foreground">
                {key === "refund_estimate" ? <ArrowDownRight className="h-3.5 w-3.5 text-primary" /> : <ArrowUpRight className="h-3.5 w-3.5" />}
                {data.readiness.tax_ready ? "Validated locally" : "Provisional — review required"}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Monthly cash flow</CardTitle>
            <CardDescription>Credits and debits after ignored rows are removed.</CardDescription>
          </CardHeader>
          <CardContent className="h-80">
            {data.monthly_flow.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.monthly_flow} margin={{ left: 0, right: 12 }}>
                  <defs>
                    <linearGradient id="credits" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.25} />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis tickFormatter={(value) => `${Math.round(value / 100000)}L`} tick={{ fontSize: 12 }} width={45} />
                  <Tooltip formatter={(value) => money(Number(value))} />
                  <Area type="monotone" dataKey="credits" stroke="hsl(var(--primary))" fill="url(#credits)" strokeWidth={2} />
                  <Area type="monotone" dataKey="debits" stroke="hsl(var(--muted-foreground))" fill="transparent" strokeWidth={1.5} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <Empty label="Upload statements to populate the chart." />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Income mix</CardTitle>
            <CardDescription>Taxable and exempt source categories.</CardDescription>
          </CardHeader>
          <CardContent className="h-80">
            {data.income_breakdown.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.income_breakdown} dataKey="value" nameKey="name" innerRadius={60} outerRadius={95} paddingAngle={3}>
                    {data.income_breakdown.map((_, index) => (
                      <Cell key={index} fill={`hsl(${160 + index * 26} 55% ${42 + (index % 3) * 8}%)`} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => money(Number(value))} />
                </PieChart>
              </ResponsiveContainer>
            ) : <Empty label="No classified income yet." />}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <QualityCard icon={AlertTriangle} label="Needs review" value={data.quality.review_count} hint="Uncertain credits and matches" />
        <QualityCard icon={Fingerprint} label="Duplicates" value={data.quality.duplicate_count} hint="Excluded from aggregation" />
        <QualityCard icon={ShieldCheck} label="Self transfers" value={data.quality.self_transfer_count} hint="Linked across own accounts" />
        <QualityCard icon={Files} label="Source documents" value={data.quality.document_count} hint="Contributing to this FY" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Detailed income summary</CardTitle>
          <CardDescription>Every figure required for the preparation workspace.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 lg:grid-cols-4">
            {detailMetrics.map((key) => (
              <div key={key} className="bg-card p-4">
                <p className="text-xs text-muted-foreground">{metricLabels[key]}</p>
                <p className="mt-1 font-semibold">{money(data.metrics[key])}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function QualityCard({ icon: Icon, label, value, hint }: { icon: typeof BadgeIndianRupee; label: string; value: number; hint: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-5">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-muted"><Icon className="h-5 w-5" /></div>
        <div><p className="text-xl font-bold">{value}</p><p className="text-sm font-medium">{label}</p><p className="text-xs text-muted-foreground">{hint}</p></div>
      </CardContent>
    </Card>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="grid h-full place-items-center text-center text-sm text-muted-foreground">{label}</div>;
}

function ErrorState({ message }: { message?: string }) {
  return <Card><CardContent className="p-8 text-center text-sm text-destructive">{message || "Could not load dashboard."}</CardContent></Card>;
}
