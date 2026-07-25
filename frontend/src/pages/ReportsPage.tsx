import { Download, FileJson, FileSpreadsheet, FileText } from "lucide-react";
import { useFinancialYear } from "@/AppContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const reports = [
  ["income-summary", "Income Summary", "Gross, taxable, exempt and net income figures", "📊"],
  ["credit-summary", "Credit Summary", "Credits grouped by inferred category", "🏷️"],
  ["tax-summary", "Tax Summary", "Old and new regime comparison", "⚖️"],
  ["bank-wise-summary", "Bank-wise Summary", "Credits, debits and row counts per bank", "🏦"],
  ["interest-summary", "Interest Summary", "Savings, FD, RD and other interest", "💰"],
  ["dividend-summary", "Dividend Summary", "Company and fund dividend receipts", "📈"],
  ["capital-gain-report", "Capital Gain Report", "FIFO STCG and LTCG lots", "📉"],
  ["salary-report", "Salary Report", "Salary credits and evidence", "💼"],
  ["rental-report", "Rental Report", "Rent receipts and related entries", "🏠"],
  ["business-report", "Business Report", "Business and professional receipts", "🏢"],
  ["expense-report", "Expense Report", "Classified expenses and business-use flags", "🧾"],
  ["ais-reconciliation", "AIS Reconciliation", "AIS matches, missing and duplicate entries", "🔍"],
  ["26as-reconciliation", "26AS Reconciliation", "Tax-credit evidence reconciliation", "📋"],
  ["deduction-report", "Deduction Report", "Suggested and accepted deductions", "✅"],
  ["review-items", "Review Items", "Uncertain items requiring confirmation", "⚠️"],
] as const;

const formats = [
  { key: "xlsx", label: "Excel", Icon: FileSpreadsheet, color: "text-emerald-600 dark:text-emerald-400", bg: "hover:bg-emerald-50 dark:hover:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800" },
  { key: "csv", label: "CSV", Icon: Download, color: "text-blue-600 dark:text-blue-400", bg: "hover:bg-blue-50 dark:hover:bg-blue-950/40 border-blue-200 dark:border-blue-800" },
  { key: "pdf", label: "PDF", Icon: FileText, color: "text-rose-600 dark:text-rose-400", bg: "hover:bg-rose-50 dark:hover:bg-rose-950/40 border-rose-200 dark:border-rose-800" },
  { key: "json", label: "JSON", Icon: FileJson, color: "text-amber-600 dark:text-amber-400", bg: "hover:bg-amber-50 dark:hover:bg-amber-950/40 border-amber-200 dark:border-amber-800" },
] as const;

export function ReportsPage() {
  const { financialYear } = useFinancialYear();
  const href = (kind: string, format: string) =>
    `/api/reports/${kind}?financial_year=${encodeURIComponent(financialYear)}&format=${format}`;

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Reports</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Download financial reports in your preferred format. All files are generated locally and
          never leave this machine.
        </p>
      </div>

      {/* Format legend */}
      <div className="flex flex-wrap gap-3">
        {formats.map(({ key, label, Icon, color }) => (
          <div
            key={key}
            className="flex items-center gap-1.5 rounded-full border bg-background px-3 py-1 text-xs font-medium"
          >
            <Icon className={`h-3.5 w-3.5 ${color}`} />
            <span>{label}</span>
          </div>
        ))}
        <span className="self-center text-xs text-muted-foreground">— available for every report below</span>
      </div>

      {/* Report grid */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {reports.map(([kind, title, description, emoji]) => (
          <Card
            key={kind}
            className="group flex flex-col transition-shadow hover:shadow-md"
          >
            <CardHeader className="pb-3">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 text-2xl leading-none" aria-hidden>
                  {emoji}
                </span>
                <div className="min-w-0">
                  <CardTitle className="text-base">{title}</CardTitle>
                  <CardDescription className="mt-0.5 text-xs leading-snug">
                    {description}
                  </CardDescription>
                </div>
              </div>
            </CardHeader>

            <CardContent className="mt-auto pt-0">
              <div className="grid grid-cols-2 gap-2">
                {formats.map(({ key, label, Icon, color, bg }) => (
                  <a
                    key={key}
                    id={`download-${kind}-${key}`}
                    href={href(kind, key)}
                    download
                    className={`inline-flex h-9 items-center justify-center gap-2 rounded-lg border bg-background px-3 text-sm font-medium transition-colors ${bg}`}
                  >
                    <Icon className={`h-3.5 w-3.5 ${color}`} />
                    <span>{label}</span>
                  </a>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
