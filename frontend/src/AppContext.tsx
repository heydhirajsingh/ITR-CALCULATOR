import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

const FinancialYearContext = createContext<{
  financialYear: string;
  setFinancialYear: (value: string) => void;
} | null>(null);

export function FinancialYearProvider({ children }: { children: ReactNode }) {
  const [financialYear, setFinancialYear] = useState(() => localStorage.getItem("itr-financial-year") || "FY 2025-26");
  const value = useMemo(
    () => ({
      financialYear,
      setFinancialYear: (next: string) => {
        setFinancialYear(next);
        localStorage.setItem("itr-financial-year", next);
      },
    }),
    [financialYear],
  );
  return <FinancialYearContext.Provider value={value}>{children}</FinancialYearContext.Provider>;
}

export function useFinancialYear() {
  const value = useContext(FinancialYearContext);
  if (!value) throw new Error("useFinancialYear must be used within FinancialYearProvider");
  return value;
}
