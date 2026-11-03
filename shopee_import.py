"""Adaptador offline para CSV de ofertas Shopee obtido por meio autorizado.
Não acessa Shopee, não cria links e não publica mensagens.
"""
import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urlparse

COLUMNS = ("source", "product_id", "title", "url", "price_brl")

def shopee_host(url):
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host == "shopee.com.br" or host.endswith(".shopee.com.br") or host == "shope.ee")

def normalize(input_path, output_path):
    count = 0
    rejected = 0
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(input_path, encoding="utf-8-sig", newline="") as inp, open(output_path, "w", encoding="utf-8", newline="") as out:
        reader = csv.DictReader(inp)
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()
        for row in reader:
            # Mapeamento explícito: CSV de 4 colunas, preparado manualmente a partir de dados autorizados.
            item_id = (row.get("product_id") or "").strip()
            title = (row.get("title") or "").strip()
            price = (row.get("price_brl") or "").strip()
            url = (row.get("affiliate_url") or "").strip()
            if not item_id or not title or not price or not shopee_host(url):
                rejected += 1
                continue
            writer.writerow({"source": "SHOPEE", "product_id": item_id,
                             "title": title, "url": url, "price_brl": price})
            count += 1
    print(json.dumps({"accepted": count, "rejected": rejected,
                      "network_requests": 0, "telegram_messages_sent": 0}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    normalize(args.input, args.output)
