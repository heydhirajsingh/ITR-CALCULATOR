import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, EyeOff, Layers3, X, Calendar, Building2, FileText, Hash } from "lucide-react";
import { useFinancialYear } from "@/AppContext";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loading } from "@/components/Loading";
import type { Transaction } from "@/types";

type ReviewItem = { review_id: number; reason: string; suggested_action: string | null; confidence: number; transaction: Transaction & { date?: string; bank?: string; page?: number | null; line?: number | null; document_filename?: string | null } };
type ReviewPage = { items: ReviewItem[]; total: number; page: number };
type ReviewGroup = { pattern: string; direction: "credit" | "debit"; count: number; total_amount: number; category: string; sample_description: string; counterparty?: string | null; confidence: number; review_ids: number[] };
type GroupPage = { items: ReviewGroup[]; groups: number; transactions: number };

const presets = {
  salary: { label: "Salary", category: "Salary", income_type: "Salary Income", taxable: true, exempt: false, ignored: false },
  interest: { label: "Interest", category: "Interest", income_type: "Interest Income", taxable: true, exempt: false, ignored: false },
  business: { label: "Business receipt", category: "Business Receipt", income_type: "Business Income", taxable: true, exempt: false, ignored: false },
  other_income: { label: "Other taxable income", category: "Other", income_type: "Other Sources", taxable: true, exempt: false, ignored: false },
  non_income: { label: "Non-income / personal", category: "Personal Receipt", income_type: null, taxable: false, exempt: false, ignored: true },
  refund: { label: "Refund / reversal", category: "Refund", income_type: null, taxable: false, exempt: false, ignored: true },
  expense: { label: "Expense", category: "Other", income_type: null, taxable: false, exempt: false, ignored: false },
} as const;

function formatDate(d: string | null | undefined) {
  if (!d) return null;
  try {
    const dt = new Date(d);
    return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return d;
  }
}

function SourceTag({ icon: Icon, label, value }: { icon: React.FC<{ className?: string }>; label: string; value: string | number | null | undefined }) {
  if (value == null) return null;
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] text-muted-foreground bg-muted/60 rounded px-1.5 py-0.5 font-mono"
      title={label}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {value}
    </span>
  );
}

export function ReviewQueuePage() {
  const { financialYear } = useFinancialYear();
  const client = useQueryClient();
  const [choices, setChoices] = useState<Record<string, keyof typeof presets>>({});

  const groups = useQuery({
    queryKey: ["review-groups", financialYear],
    queryFn: () => api<GroupPage>(`/api/review/groups?financial_year=${encodeURIComponent(financialYear)}`),
  });
  const query = useQuery({
    queryKey: ["review", financialYear],
    queryFn: () => api<ReviewPage>(`/api/review?financial_year=${encodeURIComponent(financialYear)}&page_size=50`),
  });

  const refresh = () => {
    client.invalidateQueries({ queryKey: ["review"] });
    client.invalidateQueries({ queryKey: ["review-groups"] });
    client.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const groupAction = useMutation({
    mutationFn: ({ group, choice }: { group: ReviewGroup; choice: keyof typeof presets }) => {
      const preset = presets[choice];
      return api("/api/review/groups/action", {
        method: "POST",
        body: JSON.stringify({
          financial_year: financialYear,
          pattern: group.pattern,
          direction: group.direction,
          counterparty: group.counterparty,
          ...preset,
          save_rule: true,
        }),
      });
    },
    onSuccess: refresh,
  });

  const action = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) =>
      api(`/api/review/${id}/action`, { method: "POST", body: JSON.stringify({ action: value }) }),
    onSuccess: refresh,
  });

  if (query.isLoading || groups.isLoading) return <Loading label="Grouping recurring review items" />;

  const items = query.data?.items ?? [];
  const groupedItems = groups.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Review queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Resolve recurring narrations once; the saved local rule applies to future imports.
        </p>
      </div>

      {/* ── GROUPED SECTION ────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers3 className="h-5 w-5" />
            {groups.data?.groups ?? 0} recurring groups
          </CardTitle>
          <CardDescription>
            {groups.data?.transactions ?? 0} transactions can be handled in bulk. Confirm tax treatment before applying a rule.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {groupedItems.slice(0, 100).map((group) => {
            const key = `${group.direction}:${group.pattern}`;
            const choice = choices[key] ?? (group.direction === "debit" ? "expense" : "other_income");
            const partyRole = group.direction === "credit" ? "Payer" : "Payee";
            const partyName = group.counterparty || group.sample_description;
            return (
              <div key={key} className="rounded-xl border p-4 hover:bg-muted/20 transition">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{group.count}×</Badge>
                      <Badge className="bg-muted">{group.direction}</Badge>
                      <Badge className="border border-primary/40 text-primary font-medium bg-primary/5">
                        {partyRole}: {partyName}
                      </Badge>
                      <Badge className="bg-muted">{Math.round(group.confidence)}% match</Badge>
                    </div>
                    <p className="mt-2 text-base font-bold tracking-tight text-foreground" title={partyName}>
                      {partyName}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground truncate" title={group.sample_description}>
                      Narration: {group.sample_description}
                    </p>
                    <p className="mt-0.5 text-[11px] font-mono text-muted-foreground/80">
                      Pattern:{" "}
                      {group.pattern
                        .replace(/^[-/\s]+/, "")
                        .replace(/[-/\s]+$/, "")
                        .replace(/[-/]/g, " ")
                        .replace(/\s+/g, " ")
                        .trim()
                        .replace(/\b\w/g, (c) => c.toUpperCase()) || "Standard Pattern"}
                    </p>
                  </div>
                  <p className="text-xl font-bold">{money(group.total_amount)}</p>
                  <select
                    className="h-9 rounded-lg border bg-background px-3 text-sm font-medium"
                    value={choice}
                    onChange={(event) =>
                      setChoices((value) => ({ ...value, [key]: event.target.value as keyof typeof presets }))
                    }
                  >
                    {Object.entries(presets)
                      .filter(([name]) => (group.direction === "credit" ? name !== "expense" : name === "expense"))
                      .map(([name, preset]) => (
                        <option key={name} value={name}>
                          {preset.label}
                        </option>
                      ))}
                  </select>
                  <Button size="sm" disabled={groupAction.isPending} onClick={() => groupAction.mutate({ group, choice })}>
                    <Check className="h-4 w-4 mr-1" /> Apply to {group.count}
                  </Button>
                </div>
              </div>
            );
          })}
          {!groupedItems.length && (
            <div className="p-10 text-center text-sm text-muted-foreground">
              Nothing needs review for this financial year.
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── INDIVIDUAL ITEMS SECTION ───────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>{query.data?.total ?? 0} individual items</CardTitle>
          <CardDescription>Use these controls for one-off exceptions rather than recurring patterns.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {items.map((item) => {
            const tx = item.transaction;
            const partyRole = tx.credit ? "Payer" : "Payee";
            const partyName = tx.counterparty || tx.description;
            const shortFilename = tx.document_filename
              ? tx.document_filename.replace(/\.pdf$/i, "").slice(0, 30)
              : null;
            return (
              <div key={item.review_id} className="rounded-xl border p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                  <div className="min-w-0 flex-1">
                    {/* Badges */}
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{Math.round(item.confidence)}%</Badge>
                      <Badge className="border border-primary/40 text-primary font-medium bg-primary/5">
                        {partyRole}: {partyName}
                      </Badge>
                      <Badge className="bg-muted">{tx.category}</Badge>
                    </div>

                    {/* Counterparty / description */}
                    <p className="mt-2 text-base font-bold text-foreground" title={partyName}>
                      {partyName}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground truncate" title={tx.description}>
                      Narration: {tx.description}
                    </p>

                    {/* Source metadata pills */}
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <SourceTag icon={Calendar} label="Transaction date" value={formatDate(tx.date)} />
                      <SourceTag icon={Building2} label="Bank" value={tx.bank} />
                      <SourceTag icon={FileText} label="Source PDF" value={shortFilename} />
                      {tx.page != null && (
                        <SourceTag icon={Hash} label="Page number in PDF" value={`Pg ${tx.page}`} />
                      )}
                      {tx.line != null && (
                        <SourceTag icon={Hash} label="Line number on page" value={`Ln ${tx.line}`} />
                      )}
                    </div>

                    {/* Reason */}
                    <p className="mt-1.5 text-sm text-muted-foreground">{item.reason}</p>
                  </div>

                  {/* Amount */}
                  <p
                    className={`text-lg font-bold shrink-0 ${
                      tx.credit ? "text-emerald-700 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {money(tx.amount)}
                  </p>

                  {/* Actions */}
                  <div className="flex gap-2 shrink-0">
                    <Button size="sm" onClick={() => action.mutate({ id: item.review_id, value: "accept" })}>
                      <Check className="h-4 w-4 mr-1" /> Accept
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => action.mutate({ id: item.review_id, value: "ignore" })}>
                      <EyeOff className="h-4 w-4 mr-1" /> Ignore
                    </Button>
                    <Button size="sm" variant="destructive" onClick={() => action.mutate({ id: item.review_id, value: "reject" })}>
                      <X className="h-4 w-4 mr-1" /> Reject
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
