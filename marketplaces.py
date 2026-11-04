"""Conectores oficiais de afiliados. Nunca crie tokens ou links fictícios."""
import hashlib
import json
import os
import re
import time
import urllib.request
from urllib.parse import urlparse

from offer_workflow import valid_shopee_link

class ConnectorError(ValueError):
    pass

class Marketplace:
    code = ""
    enabled = False
    def convert(self, origin_url, channel):
        raise NotImplementedError

class Shopee(Marketplace):
    code = "SHOPEE"
    enabled = True
    endpoint = "https://open-api.affiliate.shopee.com.br/graphql"
    mutation = 'mutation GenerateAffiliateLink($input: ShortLinkInput!) { generateShortLink(input: $input) { shortLink } }'

    def convert(self, origin_url, channel="telegram"):
        if not valid_shopee_link(origin_url):
            raise ConnectorError("É necessária uma URL HTTPS da Shopee")
        if channel not in ("telegram", "whatsapp"):
            raise ConnectorError("Canal inválido")
        appid = os.environ.get("SHOPEE_APP_ID", "").strip()
        secret = os.environ.get("SHOPEE_APP_SECRET", "").strip()
        if not appid or not secret:
            raise ConnectorError("Configure SHOPEE_APP_ID e SHOPEE_APP_SECRET no Easypanel")
        payload = json.dumps(
            {"query": self.mutation, "variables": {"input": {"originUrl": origin_url, "subIds": ["radarofertas", channel]}}},
            separators=(",", ":"), ensure_ascii=False
        )
        timestamp = str(int(time.time()))
        signature = hashlib.sha256((appid + timestamp + payload + secret).encode("utf-8")).hexdigest()
        header = f"SHA256 Credential={appid}, Timestamp={timestamp}, Signature={signature}"
        request = urllib.request.Request(
            self.endpoint, data=payload.encode("utf-8"), method="POST",
            headers={"Content-Type":"application/json", "Authorization":header, "Accept":"application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status != 200:
                    raise ConnectorError("Shopee não confirmou a conversão")
                result = json.load(response)
        except Exception as exc:
            raise ConnectorError("Não foi possível converter o link pela API oficial") from exc
        if result.get("errors"):
            raise ConnectorError("A Shopee retornou um erro na conversão")
        link = ((result.get("data") or {}).get("generateShortLink") or {}).get("shortLink", "")
        if not valid_shopee_link(link):
            raise ConnectorError("A API retornou um link fora dos domínios permitidos")
        return link

class Placeholder(Marketplace):
    def __init__(self, code):
        self.code = code
    def convert(self, origin_url, channel):
        raise ConnectorError(f"{self.code}: integração não habilitada")

CONNECTORS = {
    "SHOPEE": Shopee(),
    "AMAZON": Placeholder("AMAZON"),
    "MERCADO_LIVRE": Placeholder("MERCADO_LIVRE"),
    "TIKTOK_SHOP": Placeholder("TIKTOK_SHOP"),
}

def connector_for(source):
    item = CONNECTORS.get(source.upper())
    if not item:
        raise ConnectorError("Marketplace não reconhecido")
    return item
