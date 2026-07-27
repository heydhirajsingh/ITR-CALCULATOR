import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check, EyeOff, X, Calendar, Building2, FileText, Hash,
  ChevronDown, ChevronUp, Layers3,
} from "lucide-react";
import { useFinancialYear } from "@/AppContext";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loading } from "@/components/Loading";
import type { Transaction } from "@/types";

/* ── types ─────────────────────────────────────────────────────── */
type TxMeta = Transaction & {
  date?: string;
  bank?: string;
  page?: number | null;
  line?: number | null;
  document_filename?: string | null;
};

type GroupItem = {
  review_id: number;
  confidence: number;
  reason: string | null;
  transaction: TxMeta;
};

type ReviewGroup = {
  pattern: string;
  direction: "credit" | "debit";
  count: number;
  total_amount: number;
  category: string;
  sample_description: string;
  counterparty?: string | null;
  confidence: number;
  review_ids: number[];
  transactions: GroupItem[];
};

type GroupPage = { items: ReviewGroup[]; groups: number; transactions: number };

/* ── presets ────────────────────────────────────────────────────── */
const presets = {
  salary:       { label: "Salary",               category: "Salary",           income_type: "Salary Income",   taxable: true,  exempt: false, ignored: false },
  interest:     { label: "Interest",             category: "Interest",          income_type: "Interest Income", taxable: true,  exempt: false, ignored: false },
  business:     { label: "Business receipt",     category: "Business Receipt",  income_type: "Business Income", taxable: true,  exempt: false, ignored: false },
  other_income: { label: "Other taxable income", category: "Other",             income_type: "Other Sources",   taxable: true,  exempt: false, ignored: false },
  non_income:   { label: "Non-income / personal",category: "Personal Receipt",  income_type: null,              taxable: false, exempt: false, ignored: true  },
  refund:       { label: "Refund / reversal",    category: "Refund",            income_type: null,              taxable: false, exempt: false, ignored: true  },
  expense:      { label: "Expense",              category: "Other",             income_type: null,              taxable: false, exempt: false, ignored: false },
} as const;

/* ── helpers ────────────────────────────────────────────────────── */
function formatDate(d: string | null | undefined) {
  if (!d) return null;
  try {
    return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch { return d; }
}

function SourceTag({
  icon: Icon, label, value,
}: { icon: React.FC<{ className?: string }>; label: string; value: string | number | null | undefined }) {
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

/* ── individual transaction card inside an expanded group ───────── */
function TxCard({
  item,
  onAction,
  isPending,
}: {
  item: GroupItem;
  onAction: (id: number, value: string) => void;
  isPending: boolean;
}) {
  const tx = item.transaction;
  const partyName = tx.counterparty || tx.description;
  const shortFile = tx.document_filename ? tx.document_filename.replace(/\.pdf$/i, "").slice(0, 28) : null;

  return (
    <div className="rounded-lg border bg-muted/10 p-3 flex flex-col gap-2 sm:flex-row sm:items-start">
      <div className="flex-1 min-w-0">
        {/* top badges */}
        <div className="flex flex-wrap gap-1.5 items-center">
          <Badge className="border text-[10px]">{Math.round(item.confidence)}%</Badge>
          <Badge className="bg-muted text-[10px]">{tx.category}</Badge>
          {tx.credit ? (
            <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 text-[10px]">
              +{money(tx.credit)}
            </Badge>
          ) : (
            <Badge className="border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300 text-[10px]">
              -{money(tx.debit)}
            </Badge>
          )}
        </div>

        {/* party name */}
        <p className="mt-1 text-sm font-semibold truncate" title={partyName}>{partyName}</p>

        {/* narration */}
        <p className="text-xs text-muted-foreground truncate" title={tx.description}>
          {tx.description}
        </p>

        {/* source pills */}
        <div className="mt-1.5 flex flex-wrap gap-1">
          <SourceTag icon={Calendar}  label="Date"        value={formatDate(tx.date)} />
          <SourceTag icon={Building2} label="Bank"        value={tx.bank} />
          <SourceTag icon={FileText}  label="Source PDF"  value={shortFile} />
          {tx.page != null && <SourceTag icon={Hash} label="Page" value={`Pg ${tx.page}`} />}
          {tx.line != null && <SourceTag icon={Hash} label="Line" value={`Ln ${tx.line}`} />}
        </div>

        {item.reason && (
          <p className="mt-1 text-[11px] text-muted-foreground italic">{item.reason}</p>
        )}
      </div>

      {/* per-item action buttons */}
      <div className="flex gap-1.5 shrink-0 flex-wrap">
        <Button size="sm" className="h-7 text-xs px-2" disabled={isPending} onClick={() => onAction(item.review_id, "accept")}>
          <Check className="h-3 w-3 mr-1" /> Accept
        </Button>
        <Button size="sm" variant="outline" className="h-7 text-xs px-2" disabled={isPending} onClick={() => onAction(item.review_id, "ignore")}>
          <EyeOff className="h-3 w-3 mr-1" /> Ignore
        </Button>
        <Button size="sm" variant="destructive" className="h-7 text-xs px-2" disabled={isPending} onClick={() => onAction(item.review_id, "reject")}>
          <X className="h-3 w-3 mr-1" /> Reject
        </Button>
      </div>
    </div>
  );
}

/* ── main page ──────────────────────────────────────────────────── */
export function ReviewQueuePage() {
  const { financialYear } = useFinancialYear();
  const client = useQueryClient();

  // per-group: bulk preset choice
  const [choices, setChoices] = useState<Record<string, keyof typeof presets>>({});
  // per-group: whether the transactions are expanded
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const groups = useQuery({
    queryKey: ["review-groups", financialYear],
    queryFn: () => api<GroupPage>(`/api/review/groups?financial_year=${encodeURIComponent(financialYear)}`),
  });

  const refresh = () => {
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

  const itemAction = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) =>
      api(`/api/review/${id}/action`, { method: "POST", body: JSON.stringify({ action: value }) }),
    onSuccess: refresh,
  });

  if (groups.isLoading) return <Loading label="Loading review groups…" />;

  const groupedItems = groups.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Review queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Click any group to inspect its individual transactions. Apply a bulk rule or override each one separately.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers3 className="h-5 w-5" />
            {groups.data?.groups ?? 0} recurring groups
          </CardTitle>
          <CardDescription>
            {groups.data?.transactions ?? 0} transactions · click a group to expand individual entries.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!groupedItems.length && (
            <div className="p-10 text-center text-sm text-muted-foreground">
              Nothing needs review for this financial year. 🎉
            </div>
          )}

          {groupedItems.map((group) => {
            const key = `${group.direction}:${group.pattern}`;
            const choice = choices[key] ?? (group.direction === "debit" ? "expense" : "other_income");
            const isOpen = expanded[key] ?? false;
            const partyRole = group.direction === "credit" ? "Payer" : "Payee";
            const partyName = group.counterparty || group.sample_description;

            return (
              <div key={key} className="rounded-xl border overflow-hidden">
                {/* ── group header row ── */}
                <button
                  type="button"
                  className="w-full text-left p-4 hover:bg-muted/20 transition focus:outline-none"
                  onClick={() => setExpanded((s) => ({ ...s, [key]: !s[key] }))}
                >
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
                    </div>

                    <div className="flex items-center gap-3 xl:shrink-0">
                      <p className="text-xl font-bold">{money(group.total_amount)}</p>
                      {isOpen ? (
                        <ChevronUp className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                  </div>
                </button>

                {/* ── bulk action bar (always visible) ── */}
                <div
                  className="flex flex-wrap items-center gap-2 px-4 pb-3"
                  onClick={(e) => e.stopPropagation()}
                >
                  <select
                    className="h-8 rounded-lg border bg-background px-2 text-sm font-medium"
                    value={choice}
                    onChange={(e) =>
                      setChoices((v) => ({ ...v, [key]: e.target.value as keyof typeof presets }))
                    }
                  >
                    {Object.entries(presets)
                      .filter(([name]) => (group.direction === "credit" ? name !== "expense" : name === "expense"))
                      .map(([name, p]) => (
                        <option key={name} value={name}>{p.label}</option>
                      ))}
                  </select>
                  <Button
                    size="sm"
                    className="h-8"
                    disabled={groupAction.isPending}
                    onClick={() => groupAction.mutate({ group, choice })}
                  >
                    <Check className="h-3.5 w-3.5 mr-1" /> Apply to all {group.count}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    or expand to review individually ↑
                  </span>
                </div>

                {/* ── expanded individual transactions ── */}
                {isOpen && (
                  <div className="border-t bg-muted/5 px-4 py-3 space-y-2">
                    {group.transactions.map((item) => (
                      <TxCard
                        key={item.review_id}
                        item={item}
                        onAction={(id, value) => itemAction.mutate({ id, value })}
                        isPending={itemAction.isPending}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
