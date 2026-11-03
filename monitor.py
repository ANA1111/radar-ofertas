"""Monitor seguro de ofertas: importa CSV local, mantém histórico e não publica."""
import argparse
import csv
import datetime as dt
import decimal
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
 source TEXT NOT NULL, product_id TEXT NOT NULL, title TEXT NOT NULL,
 url TEXT NOT NULL, last_price_cents INTEGER NOT NULL,
 last_seen TEXT NOT NULL, PRIMARY KEY(source, product_id)
);
CREATE TABLE IF NOT EXISTS price_history (
 source TEXT NOT NULL, product_id TEXT NOT NULL,
 price_cents INTEGER NOT NULL, observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
 source TEXT NOT NULL, product_id TEXT NOT NULL,
 title TEXT NOT NULL, url TEXT NOT NULL, price_cents INTEGER NOT NULL,
 previous_cents INTEGER NOT NULL, observed_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending_review',
 UNIQUE(source, product_id, price_cents)
);
"""

def cents(value):
    price = decimal.Decimal(str(value).strip().replace(",", "."))
    if not price.is_finite() or price <= 0:
        raise ValueError("preço inválido")
    return int((price * 100).quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP))

def valid_url(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password

def import_csv(path, db_path, min_drop):
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    accepted, candidates, rejected = 0, 0, 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                source = row["source"].strip()
                product_id = row["product_id"].strip()
                title = row["title"].strip()
                url = row["url"].strip()
                price = cents(row["price_brl"])
                if not source or not product_id or not title or not valid_url(url):
                    raise ValueError("campos ou URL inválidos")
            except (KeyError, ValueError, decimal.InvalidOperation):
                rejected += 1
                continue
            previous = connection.execute(
                "SELECT last_price_cents FROM products WHERE source=? AND product_id=?",
                (source, product_id)).fetchone()
            connection.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?) ON CONFLICT(source,product_id) "
                "DO UPDATE SET title=excluded.title,url=excluded.url,"
                "last_price_cents=excluded.last_price_cents,last_seen=excluded.last_seen",
                (source, product_id, title, url, price, observed_at))
            connection.execute("INSERT INTO price_history VALUES (?,?,?,?)",
                               (source, product_id, price, observed_at))
            accepted += 1
            if previous and price < previous[0] and (previous[0]-price)*100 >= min_drop*previous[0]:
                result = connection.execute(
                    "INSERT OR IGNORE INTO candidates(source,product_id,title,url,price_cents,"
                    "previous_cents,observed_at) VALUES (?,?,?,?,?,?,?)",
                    (source, product_id, title, url, price, previous[0], observed_at))
                candidates += result.rowcount
    connection.commit()
    connection.close()
    print(json.dumps({"accepted": accepted, "rejected": rejected,
                      "new_candidates": candidates, "telegram_messages_sent": 0}))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Arquivo CSV com ofertas verificadas")
    parser.add_argument("--db", default="data/offers.sqlite3")
    parser.add_argument("--min-drop", type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.min_drop <= 99:
        parser.error("--min-drop deve estar entre 1 e 99")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    import_csv(args.csv, args.db, args.min_drop)

if __name__ == "__main__":
    main()
