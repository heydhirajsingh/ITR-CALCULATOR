import os
import sys
import traceback
from decimal import Decimal
from pathlib import Path

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.database.session import SessionLocal
from backend.app.models.entities import Document, Transaction
from backend.app.parsers.pdf import PdfParser
from backend.app.parsers.detector import detect_bank
from sqlalchemy import text

def reimport_all():
    db = SessionLocal()

    # Clear old data from dependent tables
    with db.get_bind().connect() as conn:
        conn.execute(text('PRAGMA foreign_keys = OFF'))
        tables_to_clear = [
            'review_queue', 'audit_logs', 'deductions', 'incomes', 'expenses',
            'investments', 'dividends', 'capital_gains', 'tds', 'transactions'
        ]
        for tbl in tables_to_clear:
            try:
                conn.execute(text(f'DELETE FROM {tbl}'))
            except Exception:
                pass
        conn.commit()
        conn.execute(text('PRAGMA foreign_keys = ON'))

    parser = PdfParser()
    docs = db.query(Document).all()
    total_txs = 0

    print("=================== END-TO-END RE-IMPORT ===================")
    passwords = [None, '257115168', '10115033307', '2601DHI', 'DHIR2601', '107957416']

    for doc in docs:
        path = None
        for subdir in Path('data/uploads').iterdir():
            if subdir.is_dir():
                for f in subdir.iterdir():
                    if f.name.endswith(doc.filename):
                        path = f
                        break
                if path: break

        if not path:
            print(f"File not found for Doc #{doc.id}: {doc.filename}")
            continue

        res = None
        for pw in passwords:
            try:
                res = parser.parse(path, password=pw)
                break
            except Exception as e:
                err_str = str(e).lower()
                if 'password is incorrect' in err_str or 'encrypted' in err_str or 'password is required' in err_str:
                    continue
                # If it's a parsing error, print it and break out of password loop so we don't silence it
                traceback.print_exc()
                print(f"Parsing failed for Doc #{doc.id} with pw {pw}: {e}")
                break
        
        if not res:
            print(f"Doc #{doc.id}: {doc.filename} Failed completely.")
            continue

        # Extract bank name correctly using the fixed detector
        sample_descriptions = ' '.join([str(t.description) for t in res.transactions[:10]])
        doc.bank_name = detect_bank(doc.filename, sample_descriptions) or res.document_type
        doc.parser_used = res.parser_used
        doc.status = 'completed'

        for t in res.transactions:
            new_tx = Transaction(
                document_id=doc.id,
                transaction_date=t.transaction_date,
                value_date=t.value_date,
                description=t.description,
                narration=t.narration,
                reference_number=t.reference_number,
                debit=t.debit,
                credit=t.credit,
                amount=t.debit if t.debit > Decimal('0') else t.credit,
                direction='debit' if t.debit > Decimal('0') else 'credit',
                balance=t.balance,
                bank_name=doc.bank_name,
                source_row=t.source_row,
                raw_data=dict(t.raw_data) if t.raw_data else {},
            )
            db.add(new_tx)

        db.commit()
        print(f"Doc #{doc.id}: {doc.filename[:20]:<20} | Bank: {doc.bank_name:<15} | Txs: {len(res.transactions)}")
        total_txs += len(res.transactions)

    print(f"TOTAL: {total_txs} transactions properly stored.")

if __name__ == "__main__":
    reimport_all()
