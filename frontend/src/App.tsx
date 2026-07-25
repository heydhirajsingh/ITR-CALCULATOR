// Vercel deployment build trigger
import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Calculator,
  ClipboardCheck,
  FileText,
  Menu,
  Moon,
  ReceiptText,
  Settings,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useFinancialYear } from "@/AppContext";
import type { TaxYear } from "@/types";
import { DashboardPage } from "@/pages/DashboardPage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { TransactionsPage } from "@/pages/TransactionsPage";
import { ReportsPage } from "@/pages/ReportsPage";
import { TaxSummaryPage } from "@/pages/TaxSummaryPage";
import { ReviewQueuePage } from "@/pages/ReviewQueuePage";
import { SettingsPage } from "@/pages/SettingsPage";

const navigation = [
  { to: "/", label: "Dashboard", icon: BarChart3 },
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/transactions", label: "Transactions", icon: ReceiptText },
  { to: "/reports", label: "Reports", icon: ClipboardCheck },
  { to: "/tax-summary", label: "Tax Summary", icon: Calculator },
  { to: "/review", label: "Review Queue", icon: ShieldCheck },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("itr-theme") === "dark");
  const { financialYear, setFinancialYear } = useFinancialYear();
  const years = useQuery({ queryKey: ["tax-years"], queryFn: () => api<TaxYear[]>("/api/tax-years") });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("itr-theme", dark ? "dark" : "light");
  }, [dark]);

  return (
    <div className="min-h-screen bg-background">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-72 border-r bg-card p-4 transition-transform lg:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-16 items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-primary-foreground">
              <ReceiptText className="h-5 w-5" />
            </div>
            <div>
              <p className="font-semibold">Local ITR</p>
              <p className="text-xs text-muted-foreground">Private income workspace</p>
            </div>
          </div>
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setSidebarOpen(false)}>
            <X className="h-5 w-5" />
          </Button>
        </div>
        <nav className="mt-6 space-y-1">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition hover:bg-accent hover:text-accent-foreground",
                  isActive && "bg-accent text-accent-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-4 left-4 right-4 rounded-xl border bg-muted/50 p-3 text-xs text-muted-foreground">
          <div className="mb-1 flex items-center gap-2 font-medium text-foreground">
            <ShieldCheck className="h-4 w-4 text-primary" /> Offline by design
          </div>
          Files and passwords never leave this machine.
        </div>
      </aside>

      {sidebarOpen && <button className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} aria-label="Close menu" />}

      <div className="lg:pl-72">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur md:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setSidebarOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">Indian Income Tax Return Preparation</p>
            <p className="hidden text-xs text-muted-foreground sm:block">Aggregation, reconciliation and tax estimation</p>
          </div>
          <select
            className="h-9 rounded-lg border bg-background px-3 text-sm"
            value={financialYear}
            onChange={(event) => setFinancialYear(event.target.value)}
          >
            {(years.data ?? []).map((year) => (
              <option key={year.id} value={year.financial_year}>{year.financial_year}</option>
            ))}
          </select>
          <Button variant="outline" size="icon" onClick={() => setDark((value) => !value)} aria-label="Toggle dark mode">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </header>
        <main className="p-4 md:p-6 lg:p-8">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/tax-summary" element={<TaxSummaryPage />} />
            <Route path="/review" element={<ReviewQueuePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
