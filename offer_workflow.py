"""Revisão e publicação controlada de ofertas no Telegram.

Uso: python offer_workflow.py list|preview|approve|reject|publish --id N
Sem aprovação explícita e ALLOW_TEST_SEND=true, nada é enviado.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import urllib.request
from urllib.parse import urlparse

from monitor import SCHEMA


def valid_shopee_link(value):
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.port in (None, 443)
        and not parsed.username
        and not parsed.password
        and host in {"shopee.com.br", "shope.ee", "s.shopee.com.br"}
        or (
            parsed.scheme == "https"
            and not parsed.username and not parsed.password
            and (parsed.hostname or "").lower().endswith(".shopee.com.br")
            and parsed.port in (None, 443)
        )
    )


def money(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def message_for(row):
    old, new = row["previous_cents"], row["price_cents"]
    discount = round((old - new) * 100 / old) if old > new else 0
    title = " ".join(row["title"].split())[:160]
    if not valid_shopee_link(row["url"]):
        raise ValueError("Link da Shopee inválido")
    if not discount:
        raise ValueError("Oferta sem queda de preço válida")
    # Preço anterior observado é histórico local, não preço de tabela da loja.
    return (
        f"🛍️ OFERTA ENCONTRADA\n\n"
        f"📦 {title}\n"
        f"💰 Preço monitorado: {money(new)}\n"
        f"📉 Antes no nosso monitoramento: {money(old)}\n"
        f"📊 Queda observada: {discount}%\n\n"
        f"🔗 Confira preço e disponibilidade:\n{row['url']}\n\n"
        "ℹ️ Preços e estoque podem mudar. Link pode gerar comissão de afiliado."
    )


def connect(db):
    con = sqlite3.connect(db, timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # Migração não destrutiva, preserva bancos existentes.
    con.execute("""CREATE TABLE IF NOT EXISTS publications (
        candidate_id INTEGER PRIMARY KEY,
        published_at TEXT NOT NULL,
        telegram_message_id TEXT
    )""")
    return con


def candidate(con, identifier):
    row = con.execute("SELECT rowid AS candidate_id, * FROM candidates WHERE rowid=?", (identifier,)).fetchone()
    if not row:
        raise ValueError("Oferta não encontrada")
    return row


def send_test(text):
    if os.getenv("ALLOW_TEST_SEND") != "true":
        raise ValueError("Publicação desativada: ALLOW_TEST_SEND precisa ser true")
    token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TEST_CHAT_ID")
    if not token or not chat_id:
        raise ValueError("Configure BOT_TOKEN e TEST_CHAT_ID no ambiente")
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": False}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise ValueError("Telegram não confirmou envio")
    return str(payload.get("result", {}).get("message_id", ""))


def main():
    parser = argparse.ArgumentParser(description="Controle manual de ofertas")
    parser.add_argument("action", choices=("list", "preview", "approve", "reject", "publish"))
    parser.add_argument("--id", type=int, help="ID exibido em list")
    parser.add_argument("--db", default="data/offers.sqlite3")
    args = parser.parse_args()
    if args.action != "list" and (args.id is None or args.id <= 0):
        parser.error("--id positivo é obrigatório")

    con = connect(args.db)
    try:
        if args.action == "list":
            rows = con.execute(
                "SELECT rowid AS id, title, price_cents, previous_cents, status "
                "FROM candidates ORDER BY observed_at DESC LIMIT 100"
            ).fetchall()
            print(json.dumps([dict(r) for r in rows], ensure_ascii=False))
            return
        row = candidate(con, args.id)
        if args.action == "preview":
            print(message_for(row))
        elif args.action in ("approve", "reject"):
            if row["status"] == "published":
                raise ValueError("Oferta já publicada: não pode alterar aprovação")
            new_status = "approved" if args.action == "approve" else "rejected"
            con.execute("UPDATE candidates SET status=? WHERE rowid=?", (new_status, args.id))
            con.commit()
            print(f"Oferta {args.id}: {new_status}")
        elif args.action == "publish":
            if row["status"] != "approved":
                raise ValueError("Aprovação humana obrigatória antes de publicar")
            if con.execute("SELECT 1 FROM publications WHERE candidate_id=?", (args.id,)).fetchone():
                raise ValueError("Oferta já publicada anteriormente")
            text = message_for(row)
            # Apenas o chat privado TEST_CHAT_ID é usado, nunca um canal de produção.
            mid = send_test(text)
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            con.execute("INSERT INTO publications VALUES (?,?,?)", (args.id, now, mid))
            con.execute("UPDATE candidates SET status='published' WHERE rowid=?", (args.id,))
            con.commit()
            print(f"Enviado ao canal TEST_CHAT_ID; message_id={mid}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
