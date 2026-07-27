import { useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileArchive, FileLock2, FileText, Link2, RefreshCw, Trash2, UploadCloud } from "lucide-react";
import { api } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Loading } from "@/components/Loading";
import type { DocumentItem } from "@/types";

type UploadResponse = { import_session_id: string; documents: DocumentItem[] };
type ImportStatus = {
  id: string;
  status: string;
  total_files: number;
  processed_files: number;
  total_transactions: number;
  progress: number;
  message: string | null;
  documents: DocumentItem[];
};
type Account = { id: number; name: string; masked_number: string | null; bank: string | null };

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [passwordDocument, setPasswordDocument] = useState<DocumentItem | null>(null);
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [selectedDocuments, setSelectedDocuments] = useState<Set<number>>(new Set());
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeTarget, setMergeTarget] = useState("");
  const [newAccount, setNewAccount] = useState({ bank: "", name: "", number: "" });

  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<{ items: DocumentItem[]; total: number }>("/api/documents?limit=200"),
    refetchInterval: sessionId ? 5_000 : false,
  });
  const institutions = useQuery({ queryKey: ["institutions"], queryFn: () => api<string[]>("/api/institutions") });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<Account[]>("/api/accounts") });

  const status = useQuery({
    queryKey: ["import-status", sessionId],
    queryFn: () => api<ImportStatus>(`/api/imports/${sessionId}`),
    enabled: Boolean(sessionId),
    refetchInterval: (query) => {
      const value = query.state.data?.status;
      return value === "completed" ? false : 1_500;
    },
  });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const body = new FormData();
      files.forEach((file) => body.append("files", file));
      return api<UploadResponse>("/api/documents/upload", { method: "POST", body });
    },
    onSuccess: (result) => {
      setSessionId(result.import_session_id);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      const protectedPdf = result.documents.find((document) => document.status === "password_required");
      if (protectedPdf) setPasswordDocument(protectedPdf);
    },
  });

  const passwordMutation = useMutation({
    mutationFn: () => api<{ status: string }>(`/api/documents/${passwordDocument?.id}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
    onSuccess: () => {
      setPassword("");
      setPasswordError(null);
      setPasswordDocument(null);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["import-status", sessionId] });
    },
    onError: (error: Error) => setPasswordError(error.message),
  });
  const setInstitution = useMutation({
    mutationFn: ({ document, bank }: { document: DocumentItem; bank: string }) => api(`/api/documents/${document.id}`, { method: "PATCH", body: JSON.stringify({ detected_bank: bank || null }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["institutions"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const removeDocument = useMutation({
    mutationFn: (document: DocumentItem) => api<{ status: string }>(`/api/documents/${document.id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["review"] });
    },
  });
  const clearAllData = useMutation({
    mutationFn: () => api<{ status: string }>("/api/documents/clear-all", { method: "POST" }),
    onSuccess: () => {
      setSelectedDocuments(new Set());
      setSessionId(null);
      queryClient.invalidateQueries();
    },
  });
  const mergeDocuments = useMutation({
    mutationFn: () => api<{ status: string; transactions: number }>("/api/documents/merge-account", {
      method: "POST",
      body: JSON.stringify(mergeTarget === "__new__" ? {
        document_ids: Array.from(selectedDocuments),
        bank_name: newAccount.bank.trim(),
        account_name: newAccount.name.trim(),
        account_number: newAccount.number.trim() || null,
      } : {
        document_ids: Array.from(selectedDocuments),
        target_account_id: Number(mergeTarget),
      }),
    }),
    onSuccess: () => {
      setSelectedDocuments(new Set());
      setMergeOpen(false);
      setMergeTarget("");
      setNewAccount({ bank: "", name: "", number: "" });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["institutions"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
  const chooseInstitution = (document: DocumentItem, value: string) => {
    if (value === "__custom__") {
      const custom = window.prompt("Enter the issuing bank or financial institution name", "");
      if (custom?.trim()) setInstitution.mutate({ document, bank: custom.trim() });
      return;
    }
    setInstitution.mutate({ document, bank: value });
  };
  const confirmRemoval = (document: DocumentItem) => {
    const detail = document.is_file_duplicate
      ? "This exact duplicate did not import any transactions."
      : "This also removes all transactions and derived records imported from it.";
    if (window.confirm(`Remove ${document.filename}?\n\n${detail}`)) removeDocument.mutate(document);
  };

  const onDrop = (acceptedFiles: File[]) => {
    if (acceptedFiles.length) upload.mutate(acceptedFiles);
  };
  const dropzone = useDropzone({
    onDrop,
    multiple: true,
    accept: {
      "application/pdf": [".pdf"],
      "text/csv": [".csv"],
      "text/plain": [".txt"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/zip": [".zip"],
    },
  });

  // Import status is a point-in-time snapshot. Once complete, use the document
  // query so edits such as a custom bank name cannot be overwritten by stale data.
  const liveDocuments = status.data && status.data.status !== "completed"
    ? status.data.documents
    : documents.data?.items ?? [];
  const pendingPassword = useMemo(
    () => liveDocuments.find((document) => document.status === "password_required"),
    [liveDocuments],
  );
  const selectableDocuments = useMemo(
    () => liveDocuments.filter((document) => document.status === "completed" && !document.is_file_duplicate),
    [liveDocuments],
  );
  const allSelectableAreSelected = selectableDocuments.length > 0
    && selectableDocuments.every((document) => selectedDocuments.has(document.id));
  const toggleDocument = (documentId: number, checked: boolean) => {
    setSelectedDocuments((current) => {
      const next = new Set(current);
      if (checked) next.add(documentId); else next.delete(documentId);
      return next;
    });
  };
  const toggleAllDocuments = (checked: boolean) => {
    setSelectedDocuments(checked ? new Set(selectableDocuments.map((document) => document.id)) : new Set());
  };

  if (documents.isLoading) return <Loading label="Loading document register" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Documents</h1>
        <p className="mt-1 text-sm text-muted-foreground">Drop statements, tax records, workbooks and ZIP bundles. Detection is automatic.</p>
      </div>

      <Card>
        <CardContent className="p-5">
          <div
            {...dropzone.getRootProps()}
            className={cn(
              "group cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition",
              dropzone.isDragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/60 hover:bg-muted/40",
            )}
          >
            <input {...dropzone.getInputProps()} />
            <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-primary/10 text-primary">
              <UploadCloud className="h-7 w-7" />
            </div>
            <p className="mt-4 font-semibold">{dropzone.isDragActive ? "Drop files to import" : "Drag & drop financial documents"}</p>
            <p className="mt-1 text-sm text-muted-foreground">PDF, protected PDF, Excel, CSV, TXT, DOCX or ZIP · multiple ZIP parts for one bank/year are merged safely</p>
            <Button className="mt-5" disabled={upload.isPending}>{upload.isPending ? "Uploading…" : "Choose files"}</Button>
          </div>
          {upload.isError && <p className="mt-3 text-sm text-destructive">{(upload.error as Error).message}</p>}
        </CardContent>
      </Card>

      {status.data && status.data.status !== "completed" && (
        <Card className="border-primary/30">
          <CardContent className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-medium">Import in progress</p>
                <p className="text-sm text-muted-foreground">{status.data.message}</p>
              </div>
              <Badge>{status.data.total_transactions.toLocaleString("en-IN")} transactions</Badge>
            </div>
            <Progress className="mt-4" value={status.data.progress} />
            {pendingPassword && (
              <Button variant="outline" className="mt-4" onClick={() => setPasswordDocument(pendingPassword)}>
                <FileLock2 className="h-4 w-4" /> Enter PDF password
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Import register</CardTitle>
            <CardDescription>{documents.data?.total ?? 0} local documents with parser status and warnings.</CardDescription>
          </div>
          {Boolean(liveDocuments.length) && (
            <Button
              size="sm"
              variant="outline"
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              disabled={clearAllData.isPending}
              onClick={() => {
                if (window.confirm("Are you sure you want to remove ALL imported documents, statements, and transaction data?")) {
                  clearAllData.mutate();
                }
              }}
            >
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              {clearAllData.isPending ? "Clearing..." : "Clear all data"}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {selectedDocuments.size > 0 && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
              <p className="text-sm font-medium">{selectedDocuments.size} statement{selectedDocuments.size === 1 ? "" : "s"} selected</p>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setSelectedDocuments(new Set())}>Clear</Button>
                <Button size="sm" onClick={() => setMergeOpen(true)}><Link2 className="h-4 w-4" /> Merge into account</Button>
              </div>
            </div>
          )}
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[920px] text-sm">
              <thead className="bg-muted/70 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr><th className="p-3"><input type="checkbox" aria-label="Select all completed statements" checked={allSelectableAreSelected} disabled={!selectableDocuments.length} onChange={(event) => toggleAllDocuments(event.target.checked)} /></th><th className="p-3">Document</th><th className="p-3">Detected type</th><th className="p-3">Institution</th><th className="p-3">Status</th><th className="p-3">Pages</th><th className="p-3">Imported</th><th className="p-3 text-right">Action</th></tr>
              </thead>
              <tbody>
                {liveDocuments.map((document) => (
                  <tr key={document.id} className="border-t align-top hover:bg-muted/30">
                    <td className="p-3"><input type="checkbox" aria-label={`Select ${document.filename}`} checked={selectedDocuments.has(document.id)} disabled={document.status !== "completed" || Boolean(document.is_file_duplicate)} onChange={(event) => toggleDocument(document.id, event.target.checked)} /></td>
                    <td className="p-3">
                      <div className="flex items-center gap-3">
                        <FileIcon filename={document.filename} />
                        <div className="max-w-64"><p className="truncate font-medium" title={document.filename}>{document.filename}</p><p className="truncate text-xs text-muted-foreground">{document.is_file_duplicate ? "Exact duplicate — not imported" : document.parser_used || "Waiting for parser"}</p></div>
                      </div>
                    </td>
                    <td className="p-3">{document.document_type}</td>
                    <td className="p-3"><select aria-label={`Issuing bank for ${document.filename}`} className="h-9 max-w-52 rounded-lg border bg-background px-2 text-sm" value={document.detected_bank || ""} disabled={setInstitution.isPending || document.status !== "completed"} onChange={(event) => chooseInstitution(document, event.target.value)}><option value="">Choose bank…</option>{document.detected_bank && !(institutions.data ?? []).includes(document.detected_bank) && <option value={document.detected_bank}>{document.detected_bank}</option>}{(institutions.data ?? []).map((bank) => <option key={bank} value={bank}>{bank}</option>)}<option value="__custom__">+ Add custom bank…</option></select></td>
                    <td className="p-3"><StatusBadge status={document.status} />{document.error_message && <p className="mt-1 max-w-72 text-xs text-destructive">{document.error_message}</p>}{document.warnings?.length > 0 && <p className="mt-1 max-w-72 text-xs text-amber-600">{document.warnings[0]}</p>}</td>
                    <td className="p-3">{document.page_count || "—"}</td>
                    <td className="p-3 text-muted-foreground">{formatDate(document.created_at)}</td>
                    <td className="p-3 text-right">
                      <div className="flex justify-end gap-1">
                        {document.status === "password_required" ? (
                          <Button size="sm" variant="outline" onClick={() => setPasswordDocument(document)}><FileLock2 className="h-3.5 w-3.5" /> Password</Button>
                        ) : document.status === "failed" ? (
                          <Button size="sm" variant="ghost" onClick={() => api(`/api/documents/${document.id}/reprocess`, { method: "POST" }).then(() => queryClient.invalidateQueries({ queryKey: ["documents"] }))}><RefreshCw className="h-3.5 w-3.5" /> Retry</Button>
                        ) : null}
                        <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive" disabled={removeDocument.isPending || document.status === "processing" || document.status === "queued"} onClick={() => confirmRemoval(document)} title="Remove document"><Trash2 className="h-3.5 w-3.5" /> Remove</Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!liveDocuments.length && <tr><td colSpan={8} className="p-10 text-center text-muted-foreground">No documents imported yet.</td></tr>}
              </tbody>
            </table>
          </div>
          {removeDocument.isError && <p className="mt-3 text-sm text-destructive">{(removeDocument.error as Error).message}</p>}
          {setInstitution.isError && <p className="mt-3 text-sm text-destructive">Could not save the institution: {(setInstitution.error as Error).message}</p>}
        </CardContent>
      </Card>

      <Dialog open={Boolean(passwordDocument)} onOpenChange={(open) => !open && setPasswordDocument(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Document password required</DialogTitle>
            <DialogDescription>Enter the PDF or ZIP password for <span className="font-medium text-foreground">{passwordDocument?.filename}</span>. It is held in memory only for this import and is never saved.</DialogDescription>
          </DialogHeader>
          <form onSubmit={(event) => { event.preventDefault(); passwordMutation.mutate(); }} className="space-y-4">
            <Input type="password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} placeholder="PDF password" />
            {passwordError && <p className="text-sm text-destructive">{passwordError}. Please try again.</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setPasswordDocument(null)}>Cancel</Button>
              <Button type="submit" disabled={!password || passwordMutation.isPending}>{passwordMutation.isPending ? "Checking…" : "Open PDF"}</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Merge statements into one account</DialogTitle>
            <DialogDescription>All transactions from the {selectedDocuments.size} selected statement{selectedDocuments.size === 1 ? "" : "s"} will use one account. Their financial years remain based on transaction dates.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <label><span className="mb-1 block text-sm font-medium">Target account</span><select className="h-10 w-full rounded-lg border bg-background px-3 text-sm" value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)}><option value="">Choose an account…</option>{(accounts.data ?? []).map((account) => <option key={account.id} value={String(account.id)}>{account.name} · {account.bank || "Bank unconfirmed"} · {account.masked_number || "No account number"}</option>)}<option value="__new__">+ Create a new account group…</option></select></label>
            {mergeTarget === "__new__" && <div className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2"><label><span className="mb-1 block text-sm font-medium">Bank</span><Input list="merge-bank-options" value={newAccount.bank} onChange={(event) => setNewAccount((current) => ({ ...current, bank: event.target.value }))} placeholder="Bank or institution" /><datalist id="merge-bank-options">{(institutions.data ?? []).map((bank) => <option key={bank} value={bank} />)}</datalist></label><label><span className="mb-1 block text-sm font-medium">Account name</span><Input value={newAccount.name} onChange={(event) => setNewAccount((current) => ({ ...current, name: event.target.value }))} placeholder="e.g. HDFC business account" /></label><label className="sm:col-span-2"><span className="mb-1 block text-sm font-medium">Account number or last 4 digits <span className="font-normal text-muted-foreground">(optional)</span></span><Input value={newAccount.number} onChange={(event) => setNewAccount((current) => ({ ...current, number: event.target.value }))} placeholder="Used only for local grouping" /></label></div>}
            {mergeDocuments.isError && <p className="text-sm text-destructive">{(mergeDocuments.error as Error).message}</p>}
            <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setMergeOpen(false)}>Cancel</Button><Button disabled={!mergeTarget || (mergeTarget === "__new__" && (!newAccount.bank.trim() || !newAccount.name.trim())) || mergeDocuments.isPending} onClick={() => mergeDocuments.mutate()}>{mergeDocuments.isPending ? "Merging…" : "Merge statements"}</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function FileIcon({ filename }: { filename: string }) {
  const Icon = filename.toLowerCase().endsWith(".zip") ? FileArchive : filename.toLowerCase().endsWith(".pdf") ? FileText : FileText;
  return <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted"><Icon className="h-4 w-4" /></div>;
}

function StatusBadge({ status }: { status: DocumentItem["status"] }) {
  const config = {
    completed: ["Complete", "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400", CheckCircle2],
    password_required: ["Password required", "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400", FileLock2],
    failed: ["Failed safely", "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-400", AlertCircle],
    processing: ["Processing", "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400", RefreshCw],
    queued: ["Queued", "border-slate-500/30 bg-slate-500/10", RefreshCw],
    uploaded: ["Uploaded", "border-slate-500/30 bg-slate-500/10", UploadCloud],
    skipped: ["Skipped", "border-slate-500/30 bg-slate-500/10", AlertCircle],
  } as const;
  const [label, className, Icon] = config[status];
  return <Badge className={className}><Icon className={cn("mr-1 h-3 w-3", status === "processing" && "animate-spin")} />{label}</Badge>;
}
