from backend.app.database.session import SessionLocal
from backend.app.models.entities import Transaction, ReviewQueue, User
from backend.app.classification.engine import classifier
from sqlalchemy import text

db = SessionLocal()

# Fix tax year IDs
db.execute(text("UPDATE transactions SET tax_year_id = 4 WHERE transaction_date >= '2025-04-01' AND transaction_date <= '2026-03-31'"))
db.execute(text("UPDATE transactions SET tax_year_id = 3 WHERE transaction_date >= '2024-04-01' AND transaction_date <= '2025-03-31'"))
db.commit()
print('Tax years updated.')

# Rebuild review queue
db.execute(text('DELETE FROM review_queue'))
db.commit()

user = db.query(User).first()
txs = db.query(Transaction).all()

for tx in txs:
    res = classifier.classify(tx.description, debit=float(tx.debit or 0), credit=float(tx.credit or 0), user=user)
    tx.counterparty = res.counterparty
    tx.mode = res.mode
    tx.category = res.category
    rq = ReviewQueue(
        transaction_id=tx.id,
        document_id=tx.document_id,
        status='pending',
        confidence=res.confidence,
        reason='Auto-classified'
    )
    db.add(rq)

db.commit()
print(f'Classified {len(txs)} transactions and rebuilt review queue.')

# Auto-resolve self transfers
txs_self = db.query(Transaction).filter(Transaction.category == 'Self Transfer').all()
count = 0
for tx in txs_self:
    rq = db.query(ReviewQueue).filter_by(transaction_id=tx.id).first()
    if rq and rq.status != 'resolved':
        rq.status = 'resolved'
        rq.resolution_notes = 'Auto-resolved: Self Transfer (exempt from tax)'
        count += 1
db.commit()
print(f'Auto-resolved {count} self transfers.')

# Verify page/line is now in raw_data
sample = db.query(Transaction).filter(Transaction.raw_data != None).first()
if sample:
    print(f'Sample raw_data keys: {list(sample.raw_data.keys())}')
    print(f'page={sample.raw_data.get("page")}  line={sample.raw_data.get("line")}')
