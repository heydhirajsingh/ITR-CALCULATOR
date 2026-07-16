export type TaxYear = {
  id: number;
  financial_year: string;
  assessment_year: string;
  starts_on: string;
  ends_on: string;
  is_active: boolean;
  rule_version: string;
};

export type Transaction = {
  id: number;
  date: string;
  description: string;
  debit: number;
  credit: number;
  amount: number;
  balance: number | null;
  category: string;
  income_type: string | null;
  counterparty: string | null;
  bank: string | null;
  taxable: boolean;
  exempt: boolean;
  ignored: boolean;
  is_duplicate: boolean;
  duplicate_of_id: number | null;
  is_self_transfer: boolean;
  linked_transaction_id: number | null;
  needs_review: boolean;
  confidence: number;
  mode: string | null;
  document_filename: string | null;
  document_type: string | null;
};

export type DocumentItem = {
  id: number;
  filename: string;
  document_type: string;
  status: "uploaded" | "password_required" | "queued" | "processing" | "completed" | "failed" | "skipped";
  is_encrypted: boolean;
  page_count: number;
  parser_used: string | null;
  detected_bank?: string | null;
  error_message: string | null;
  warnings: string[];
  is_file_duplicate?: boolean;
  created_at: string;
};
