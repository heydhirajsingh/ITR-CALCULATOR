import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Pencil, Search, ShieldAlert } from "lucide-react";
import { useFinancialYear } from "@/AppContext";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Loading } from "@/components/Loading";
import type { Transaction } from "@/types";

type TransactionPage = { items: Transaction[]; page: number; page_size: number; total: number; pages: number };

const categories = ["Salary", "Interest", "FD Interest", "Dividend", "Rent", "Capital Gain", "Business Receipt", "Professional Income", "Gift", "Refund", "Cash Deposit", "Loan Received", "Transfer", "Investment", "Stock Sale", "Foreign Income", "Reimbursement", "Other"];

export function TransactionsPage() {
  const { financialYear } = useFinancialYear();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const query = useQuery({
    queryKey: ["transactions", financialYear, page, search, category, reviewOnly],
    queryFn: () => {
      const params = new URLSearchParams({ financial_year: financialYear, page: String(page), page_size: "50" });
      if (search) params.set("search", search);
      if (category) params.set("category", category);
      if (reviewOnly) params.set("review_only", "true");
      return api<TransactionPage>(`/api/transactions?${params}`);
    },
    placeholderData: (previous) => previous,
  });
  const update = useMutation({
    mutationFn: (payload: Partial<Transaction>) => api<Transaction>(`/api/transactions/${editing?.id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  if (query.isLoading) return <Loading label="Loading transactions" />;
  const data = query.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>
        <p className="mt-1 text-sm text-muted-foreground">Search, filter and override classification without changing the original source file.</p>
      </div>
      <Card>
        <CardContent className="grid gap-3 p-4 md:grid-cols-[1fr_220px_auto]">
          <div className="relative"><Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" /><Input className="pl-9" placeholder="Narration, UTR, counterparty or reference" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} /></div>
          <select className="h-10 rounded-lg border bg-background px-3 text-sm" value={category} onChange={(event) => { setCategory(event.target.value); setPage(1); }}><option value="">All categories</option>{categories.map((value) => <option key={value}>{value}</option>)}</select>
          <Button variant={reviewOnly ? "default" : "outline"} onClick={() => { setReviewOnly((value) => !value); setPage(1); }}><ShieldAlert className="h-4 w-4" /> Needs review</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div><CardTitle>Transaction register</CardTitle><CardDescription>{data?.total.toLocaleString("en-IN") ?? 0} rows · server-side pagination for large files</CardDescription></div>
          <Badge>{financialYear}</Badge>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[1180px] text-sm">
              <thead className="bg-muted/70 text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="p-3">Date</th><th className="p-3">Narration</th><th className="p-3">Bank</th><th className="p-3">Category</th><th className="p-3 text-right">Debit</th><th className="p-3 text-right">Credit</th><th className="p-3">Tax treatment</th><th className="p-3">Confidence</th><th className="p-3 text-right">Edit</th></tr></thead>
              <tbody>
                {(data?.items ?? []).map((transaction) => (
                  <tr key={transaction.id} className="border-t hover:bg-muted/30">
                    <td className="whitespace-nowrap p-3">{transaction.date}</td>
                    <td className="max-w-[360px] p-3"><p className="truncate font-medium" title={transaction.description}>{transaction.description}</p><p className="truncate text-xs text-muted-foreground">{transaction.counterparty || transaction.document_filename || "—"}</p></td>
                    <td className="p-3">{transaction.bank || "—"}</td>
                    <td className="p-3"><Badge className="bg-muted">{transaction.category}</Badge>{transaction.is_duplicate && <Badge className="ml-1 border-amber-500/40 text-amber-700">Duplicate</Badge>}{transaction.is_self_transfer && <Badge className="ml-1 border-blue-500/40 text-blue-700">Self transfer</Badge>}</td>
                    <td className="p-3 text-right text-red-600 dark:text-red-400">{transaction.debit ? money(transaction.debit) : "—"}</td>
                    <td className="p-3 text-right text-emerald-700 dark:text-emerald-400">{transaction.credit ? money(transaction.credit) : "—"}</td>
                    <td className="p-3">{transaction.ignored ? <Badge>Ignored</Badge> : transaction.taxable ? <Badge className="border-red-500/30 bg-red-500/10 text-red-700">Taxable</Badge> : transaction.exempt ? <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700">Exempt</Badge> : <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-700">Review</Badge>}</td>
                    <td className="p-3"><div className="flex items-center gap-2"><div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${transaction.confidence}%` }} /></div><span>{Math.round(transaction.confidence)}%</span></div></td>
                    <td className="p-3 text-right"><Button variant="ghost" size="icon" onClick={() => setEditing(transaction)}><Pencil className="h-4 w-4" /></Button></td>
                  </tr>
                ))}
                {!data?.items.length && <tr><td colSpan={9} className="p-10 text-center text-muted-foreground">No matching transactions.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between text-sm"><p className="text-muted-foreground">Page {data?.page ?? 1} of {Math.max(data?.pages ?? 1, 1)}</p><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft className="h-4 w-4" /> Previous</Button><Button variant="outline" size="sm" disabled={page >= (data?.pages ?? 1)} onClick={() => setPage((value) => value + 1)}>Next <ChevronRight className="h-4 w-4" /></Button></div></div>
        </CardContent>
      </Card>

      <EditTransaction transaction={editing} onClose={() => setEditing(null)} onSave={(payload) => update.mutate(payload)} pending={update.isPending} error={update.error as Error | null} />
    </div>
  );
}

function EditTransaction({ transaction, onClose, onSave, pending, error }: { transaction: Transaction | null; onClose: () => void; onSave: (payload: Partial<Transaction>) => void; pending: boolean; error: Error | null }) {
  const [form, setForm] = useState<Partial<Transaction>>({});
  const value = { ...transaction, ...form };
  return <Dialog open={Boolean(transaction)} onOpenChange={(open) => !open && onClose()}><DialogContent><DialogHeader><DialogTitle>Edit classification</DialogTitle><DialogDescription>Manual overrides are auditable and survive reclassification.</DialogDescription></DialogHeader>{transaction && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); onSave(form); }}><div><label className="mb-1 block text-sm font-medium">Category</label><select className="h-10 w-full rounded-lg border bg-background px-3 text-sm" value={value.category || "Other"} onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))}>{categories.map((item) => <option key={item}>{item}</option>)}</select></div><div><label className="mb-1 block text-sm font-medium">Income type</label><Input value={value.income_type || ""} onChange={(event) => setForm((current) => ({ ...current, income_type: event.target.value }))} placeholder="Salary Income, Interest Income…" /></div><div className="grid grid-cols-2 gap-3">{(["taxable", "exempt", "ignored", "needs_review"] as const).map((key) => <label key={key} className="flex items-center gap-2 rounded-lg border p-3 text-sm"><input type="checkbox" checked={Boolean(value[key])} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.checked }))} />{key.replace("_", " ")}</label>)}</div>{error && <p className="text-sm text-destructive">{error.message}</p>}<div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={onClose}>Cancel</Button><Button type="submit" disabled={pending}>{pending ? "Saving…" : "Save override"}</Button></div></form>}</DialogContent></Dialog>;
}
