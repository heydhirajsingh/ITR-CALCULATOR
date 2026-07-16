import { Download, FileJson, FileSpreadsheet, FileText } from "lucide-react";
import { useFinancialYear } from "@/AppContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const reports = [
  ["income-summary", "Income Summary", "Gross, taxable, exempt and net income figures"],
  ["credit-summary", "Credit Summary", "Credits grouped by inferred category"],
  ["tax-summary", "Tax Summary", "Old and new regime comparison"],
  ["bank-wise-summary", "Bank-wise Summary", "Credits, debits and row counts per bank"],
  ["interest-summary", "Interest Summary", "Savings, FD, RD and other interest"],
  ["dividend-summary", "Dividend Summary", "Company and fund dividend receipts"],
  ["capital-gain-report", "Capital Gain Report", "FIFO STCG and LTCG lots"],
  ["salary-report", "Salary Report", "Salary credits and evidence"],
  ["rental-report", "Rental Report", "Rent receipts and related entries"],
  ["business-report", "Business Report", "Business and professional receipts"],
  ["expense-report", "Expense Report", "Classified expenses and business-use flags"],
  ["ais-reconciliation", "AIS Reconciliation", "AIS matches, missing and duplicate entries"],
  ["26as-reconciliation", "26AS Reconciliation", "Tax-credit evidence reconciliation"],
  ["deduction-report", "Deduction Report", "Suggested and accepted deductions"],
  ["review-items", "Review Items", "Uncertain items requiring confirmation"],
] as const;

const formats = [
  ["xlsx", "Excel", FileSpreadsheet],
  ["csv", "CSV", Download],
  ["pdf", "PDF", FileText],
  ["json", "JSON", FileJson],
] as const;

export function ReportsPage() {
  const { financialYear } = useFinancialYear();
  const href = (kind: string, format: string) => `/api/reports/${kind}?financial_year=${encodeURIComponent(financialYear)}&format=${format}`;
  return <div className="space-y-6"><div><h1 className="text-2xl font-bold tracking-tight">Reports</h1><p className="mt-1 text-sm text-muted-foreground">Select a labelled format below. Downloads use the current tab and are not blocked as popups.</p></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{reports.map(([kind, title, description]) => <Card key={kind}><CardHeader><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader><CardContent><div className="grid grid-cols-2 gap-2">{formats.map(([format, label, Icon]) => <a key={format} href={href(kind, format)} download className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border bg-background px-3 text-sm font-medium transition hover:bg-accent"><Icon className="h-4 w-4" />{label}</a>)}</div></CardContent></Card>)}</div></div>;
}
