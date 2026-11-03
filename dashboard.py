"""Radar de Ofertas: painel somente leitura, sem dependências externas."""
import base64
import hashlib
import hmac
import html
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import os
import secrets
import sqlite3
import time
from collections import defaultdict
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

DB = os.environ.get("RADAR_DB", "/data/ofertas.sqlite3")
PASSWORD_HASH = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "")
PORT = int(os.environ.get("PORT", "8080"))
ATTEMPTS = defaultdict(list)
COOKIE_NAME = "radar_session"

CSS = """
:root{color-scheme:dark;--bg:#0a101c;--card:#141e30;--line:#2b3951;--text:#f0f5ff;--muted:#9daec6;--accent:#5fe0c1}
*{box-sizing:border-box}body{margin:0;font:15px system-ui,-apple-system,Segoe UI,sans-serif;background:radial-gradient(circle at top right,#163c4d 0,#0a101c 42%);color:var(--text);min-height:100vh}
a{color:var(--accent)}.wrap{max-width:1150px;margin:auto;padding:28px 20px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:32px}
.brand{font-weight:800;font-size:22px;letter-spacing:-.5px}.brand span{color:var(--accent)}.muted{color:var(--muted)}.pill{border:1px solid #3d746d;border-radius:99px;padding:7px 12px;color:#b7ffec;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px}.card{background:linear-gradient(145deg,#17253a,#111a2a);border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:0 14px 35px #0002}
.kpi{font-size:32px;font-weight:800;margin:14px 0 0}.section{margin-top:26px}h1{font-size:30px;margin:0 0 8px}h2{font-size:19px;margin:0 0 16px}
table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:14px 10px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}td{font-size:14px}.scroll{overflow:auto}
button{background:var(--accent);color:#08231f;border:0;border-radius:10px;padding:12px 18px;font-weight:750;cursor:pointer}
input{width:100%;padding:13px;background:#0b1422;border:1px solid #40516a;border-radius:10px;color:white;font:inherit;margin:8px 0 18px}
.login{max-width:430px;margin:10vh auto;padding:32px}.error{color:#ff9eab}.notice{border:1px solid #446175;padding:14px;border-radius:12px;color:#b6cce0}
.reject{background:#743543;color:#fff}.reject:hover{background:#943d50}form input[type=hidden]{display:none}.logout{background:transparent;border:1px solid #52627c;color:white;padding:9px 13px}
@media(max-width:850px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.grid{grid-template-columns:1fr 1fr;gap:9px}.card{padding:15px}.kpi{font-size:25px}.wrap{padding:18px 12px}h1{font-size:24px}th,td{padding:12px 8px}}
"""

def esc(value):
    return html.escape(str(value), quote=True)

def money(cents):
    return "R$ " + f"{cents/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def password_ok(password):
    try:
        kind, rounds, salt, expected = PASSWORD_HASH.split("$")
        if kind != "pbkdf2_sha256" or int(rounds) < 200000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

def signature(value):
    return hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

def session_token():
    expiry = str(int(time.time()) + 8 * 3600)
    nonce = secrets.token_hex(16)
    payload = expiry + "." + nonce
    return payload + "." + signature(payload)

def authenticated(cookie_header):
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header or "")
        token = cookie[COOKIE_NAME].value
        expiry, nonce, sig = token.split(".")
        payload = expiry + "." + nonce
        return int(expiry) > time.time() and hmac.compare_digest(sig, signature(payload))
    except (KeyError, ValueError):
        return False


def manual_db():
    con = sqlite3.connect(DB, timeout=5)
    con.execute("""CREATE TABLE IF NOT EXISTS manual_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, affiliate_url TEXT NOT NULL UNIQUE,
        price_cents INTEGER NOT NULL, commission_percent TEXT,
        sub_id TEXT, status TEXT NOT NULL DEFAULT 'pending_review',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    )""")
    con.commit()
    return con

def manual_list():
    con = manual_db()
    try:
        return con.execute("SELECT id,title,affiliate_url,price_cents,commission_percent,sub_id,status FROM manual_offers ORDER BY id DESC LIMIT 50").fetchall()
    finally:
        con.close()

def parse_price(raw):
    raw = raw.strip().replace("R$", "").replace(" ", "").replace(",", ".")
    value = Decimal(raw)
    if not value.is_finite() or value <= 0 or value > 9999999 or value.as_tuple().exponent < -2:
        raise ValueError("Preço inválido")
    return int(value * 100)

def offer_description(title, url, cents):
    return ("📡 ACHADINHO DO RADAR DE OFERTAS!\\n\\n"
            "🛍️ " + title + "\\n"
            "💰 Preço observado: " + money(cents) + "\\n\\n"
            "🔗 Confira: " + url + "\\n\\n"
            "⚠️ Preço e disponibilidade podem mudar. Confira na Shopee.\\n"
            "ℹ️ Link de afiliada: podemos receber comissão por compras qualificadas.")

def stats():
    # SQLite URI mode=ro garante que o painel nunca altere o banco.
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True, timeout=2)
    try:
        products = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        history = con.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        pending = con.execute("SELECT COUNT(*) FROM candidates WHERE status='pending_review'").fetchone()[0]
        candidates = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        recent = con.execute("SELECT title,price_cents,previous_cents,status,observed_at FROM candidates ORDER BY observed_at DESC LIMIT 20").fetchall()
        return products, history, pending, candidates, recent
    finally:
        con.close()

def layout(body, title="Radar de Ofertas"):
    return ("<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='robots' content='noindex,nofollow'><title>" + esc(title) +
            "</title><style>" + CSS + "</style></head><body>" + body + "</body></html>")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Não registrar cookies, tokens, senhas ou corpos de requisição.
        print("HTTP", self.command, self.path.split("?")[0], args[1] if len(args)>1 else "", flush=True)

    def respond(self, status, body, headers=None):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        for k,v in (headers or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(raw)

    def redirect(self, path, cookie=None):
        headers = {"Location":path}
        if cookie:
            headers["Set-Cookie"] = cookie
        self.respond(HTTPStatus.SEE_OTHER, "", headers)

    def login(self, error=""):
        message = "<p class='error'>Senha incorreta ou muitas tentativas. Tente novamente mais tarde.</p>" if error else ""
        body = ("<main class='wrap'><div class='card login'><div class='brand'>◉ Radar <span>de Ofertas</span></div>"
                "<p class='muted'>Acesso restrito ao painel administrativo</p>" + message +
                "<form method='post' action='/login'><label for='password'>Senha</label>"
                "<input id='password' name='password' type='password' autocomplete='current-password' required maxlength='200'>"
                "<button type='submit'>Entrar no painel</button></form>"
                "<p class='muted'>Monitoramento em modo de testes. Publicação automática desativada.</p></div></main>")
        self.respond(200, layout(body, "Login — Radar de Ofertas"))

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, "OK")
            return
        if self.path.startswith("/description?"):
            if not authenticated(self.headers.get("Cookie")):
                self.login()
                return
            try:
                query = parse_qs(urlsplit(self.path).query)
                raw_id = query.get("id", [""])[0]
                if not raw_id.isdecimal() or not 1 <= int(raw_id) <= 9223372036854775807:
                    raise ValueError("ID inválido")
                con = manual_db()
                try:
                    offer = con.execute("SELECT title,affiliate_url,price_cents FROM manual_offers WHERE id=?", (int(raw_id),)).fetchone()
                finally:
                    con.close()
                if not offer:
                    self.respond(404, "Oferta não encontrada")
                    return
                message = offer_description(*offer)
                body = ("<main class='wrap'><h1>Descrição sugerida</h1><p class='muted'>"
                        "Revise os dados antes de divulgar. Nenhum envio é realizado.</p>"
                        "<div class='card'><textarea readonly rows='12' style='width:100%;background:#0b1422;color:white;padding:14px;border:1px solid #40516a;border-radius:10px;font:inherit'>"
                        + esc(message) + "</textarea><p>Selecione e copie o texto para usar.</p>"
                        "<a href='/'>Voltar ao painel</a></div></main>")
                self.respond(200, layout(body))
            except (ValueError, sqlite3.Error):
                self.respond(400, "Não foi possível gerar a descrição")
            return
        if self.path != "/":
            self.respond(404, "Página não encontrada")
            return
        if not authenticated(self.headers.get("Cookie")):
            self.login()
            return
        try:
            products, history, pending, candidates, recent = stats()
            notice = ""
        except sqlite3.Error:
            products = history = pending = candidates = 0
            recent = []
            notice = "<p class='notice'>Banco indisponível. Verifique o volume de leitura no Easypanel.</p>"

        try:
            manual = manual_list()
            manual_rows = "".join(
                "<tr><td>"+esc(t)+"</td><td>"+money(p)+"</td><td>"+esc(c or "—")+
                "</td><td>"+esc(sub or "—")+"</td><td>"+esc(st)+
                "</td><td><a target='_blank' rel='noopener noreferrer' href='"+esc(u)+
                "'>Abrir</a> · <a href='/description?id="+esc(oid)+"'>Gerar descrição</a></td><td>"+
                ("<form method='post' action='/review' style='display:flex;gap:6px;flex-wrap:wrap'>"
                 "<input type='hidden' name='offer_id' value='"+esc(oid)+"'>"
                 "<button type='submit' name='decision' value='approved'>Aprovar</button>"
                 "<button class='reject' type='submit' name='decision' value='rejected'>Rejeitar</button>"
                 "</form>" if st == "pending_review" else "<span class='muted'>Revisado</span>")+
                "</td></tr>"
                for oid,t,u,p,c,sub,st in manual)
        except sqlite3.Error:
            manual_rows = "<tr><td colspan='7'>Banco manual indisponível. Verifique o volume /data.</td></tr>"
        if not manual_rows:
            manual_rows = "<tr><td colspan='7'>Nenhuma oferta manual cadastrada.</td></tr>"
        form_html = """<section class='card section'><h2>Cadastrar oferta Shopee</h2>
        <p class='muted'>Cadastro manual, sem publicação automática.</p>
        <form method='post' action='/offers'>
        <label>Produto<input name='title' maxlength='160' required></label>
        <label>Link de afiliada<input name='affiliate_url' type='url' maxlength='1000' required></label>
        <label>Preço observado (R$)<input name='price' placeholder='69,90' required></label>
        <label>Comissão exibida (%)<input name='commission' placeholder='28'></label>
        <label>Sub ID<input name='sub_id' maxlength='60' placeholder='radarofertas'></label>
        <button type='submit'>Salvar para revisão</button></form></section>"""
        manual_html = "<section class='card section'><h2>Ofertas cadastradas manualmente</h2><div class='scroll'><table><thead><tr><th>Produto</th><th>Preço</th><th>Comissão %</th><th>Sub ID</th><th>Status</th><th>Link</th><th>Ações</th></tr></thead><tbody>"+manual_rows+"</tbody></table></div></section>"
        metrics = [("Produtos monitorados",products),("Leituras registradas",history),("Aguardando revisão",pending),("Oportunidades detectadas",candidates)]
        cards = "".join("<div class='card'><div class='muted'>" + esc(k) + "</div><div class='kpi'>" + esc(v) + "</div></div>" for k,v in metrics)
        rows = "".join("<tr><td>" + esc(title) + "</td><td>" + money(price) + "</td><td>" +
                       money(old) + "</td><td>" + esc(status) + "</td><td>" + esc(date[:19].replace("T"," ")) +
                       "</td></tr>" for title,price,old,status,date in recent)
        if not rows:
            rows = "<tr><td colspan='5' class='muted'>Nenhuma oportunidade registrada ainda.</td></tr>"
        body = ("<main class='wrap'><header class='top'><div class='brand'>◉ Radar <span>de Ofertas</span></div>"
                "<div style='display:flex;align-items:center;gap:10px'><span class='pill'>● Modo de testes</span>"
                "<form method='post' action='/logout'><button class='logout'>Sair</button></form></div></header>"
                "<h1>Visão geral</h1><p class='muted'>Acompanhamento dos dados registrados pelo monitor. Atualize a página para consultar novamente.</p>"
                + notice + "<div class='grid'>" + cards + "</div>" + form_html + manual_html +
                "<section class='card section'><h2>Últimas oportunidades</h2><div class='scroll'>"
                "<table><thead><tr><th>Produto</th><th>Preço</th><th>Anterior</th><th>Status</th><th>Data (UTC)</th></tr></thead>"
                "<tbody>" + rows + "</tbody></table></div></section>"
                "<section class='section notice'>🔒 Cadastro manual. Nenhuma oferta é publicada automaticamente.</section></main>")
        self.respond(200, layout(body))

    def do_POST(self):
        if self.path not in ("/login","/logout","/offers","/review"):
            self.respond(404, "Página não encontrada")
            return
        # Compare com a origem HTTPS pública configurada, não com o Host interno do proxy.
        # Easypanel pode preservar um Host interno diferente do domínio visto pelo navegador.
        from urllib.parse import urlsplit
        origin = (self.headers.get("Origin") or "").strip()
        public_origin = os.environ.get("DASHBOARD_PUBLIC_ORIGIN", "").strip().strip('"').strip("'").rstrip("/")
        if not public_origin:
            self.respond(503, "Configure DASHBOARD_PUBLIC_ORIGIN no Easypanel")
            return
        expected = urlsplit(public_origin)
        actual = urlsplit(origin)
        referer = urlsplit((self.headers.get("Referer") or "").strip())
        fetch_site = (self.headers.get("Sec-Fetch-Site") or "").lower().strip()
        expected_ok = (expected.scheme == "https"
                       and expected.hostname == "ofertas.gestoncuid.tech"
                       and expected.path in ("", "/"))
        origin_ok = (actual.scheme == "https"
                     and actual.netloc.lower() == expected.netloc.lower())
        # Alguns navegadores enviam Origin: null por políticas de privacidade.
        # Só aceitar esse caso se Referer HTTPS E Fetch Metadata confirmarem
        # uma navegação same-origin; nunca confiar apenas em Origin: null.
        null_origin_same_site = (
            origin == "null"
            and fetch_site == "same-origin"
            and referer.scheme == "https"
            and referer.netloc.lower() == expected.netloc.lower()
        )
        if not (expected_ok and (origin_ok or null_origin_same_site)):
            print("ORIGIN_CHECK_REJECTED",
                  "origin="+repr(origin),
                  "fetch_site="+repr(fetch_site),
                  "referer_host="+repr(referer.netloc),
                  "configured="+repr(public_origin), flush=True)
            self.respond(403, "Origem não permitida")
            return
        if self.path == "/logout":
            self.redirect("/", COOKIE_NAME + "=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict")
            return

        if self.path == "/review":
            if not authenticated(self.headers.get("Cookie")):
                self.respond(401, "Faça login novamente")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 256:
                    raise ValueError("Requisição inválida")
                form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
                raw_id = form.get("offer_id", [""])[0]
                decision = form.get("decision", [""])[0]
                if not raw_id.isdecimal() or not 1 <= int(raw_id) <= 9223372036854775807 or decision not in ("approved", "rejected"):
                    raise ValueError("Decisão inválida")
                con = manual_db()
                try:
                    cursor = con.execute("UPDATE manual_offers SET status=? WHERE id=? AND status='pending_review'", (decision, int(raw_id)))
                    con.commit()
                    changed = cursor.rowcount
                finally:
                    con.close()
                if not changed:
                    self.respond(409, layout("<main class='wrap'><h2>Oferta já revisada ou inexistente</h2><a href='/'>Voltar</a></main>"))
                    return
            except (ValueError, UnicodeDecodeError):
                self.respond(400, "Requisição de revisão inválida")
                return
            except sqlite3.Error:
                self.respond(503, "Banco indisponível para revisão")
                return
            self.redirect("/")
            return

        if self.path == "/offers":
            if not authenticated(self.headers.get("Cookie")):
                self.respond(401, "Faça login novamente")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 4096:
                    raise ValueError("Requisição inválida")
                form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
                get = lambda key: form.get(key, [""])[0].strip()
                title, url = get("title"), get("affiliate_url")
                price = parse_price(get("price"))
                commission, sub_id = get("commission"), get("sub_id")
                parsed = urlsplit(url)
                if not 3 <= len(title) <= 160 or len(url) > 1000 or parsed.scheme != "https" or parsed.hostname not in ("s.shopee.com.br","shopee.com.br","www.shopee.com.br") or not parsed.path.strip("/") or parsed.username or parsed.password:
                    raise ValueError("Produto ou link Shopee inválido")
                if commission:
                    rate = Decimal(commission.replace(",", "."))
                    if not rate.is_finite() or rate < 0 or rate > 100 or len(commission) > 12:
                        raise ValueError("Comissão inválida")
                    commission = str(rate)
                if not re.fullmatch(r"[A-Za-z0-9_-]{0,60}", sub_id):
                    raise ValueError("Sub ID inválido")
                con = manual_db()
                try:
                    con.execute("INSERT INTO manual_offers (title,affiliate_url,price_cents,commission_percent,sub_id) VALUES (?,?,?,?,?)", (title,url,price,commission,sub_id))
                    con.commit()
                finally:
                    con.close()
            except (ValueError, InvalidOperation, UnicodeDecodeError, sqlite3.IntegrityError) as exc:
                self.respond(400, layout("<main class='wrap'><h2>Não foi possível salvar</h2><p>"+esc(str(exc))+"</p><a href='/'>Voltar</a></main>"))
                return
            except sqlite3.Error:
                self.respond(503, "Banco indisponível para escrita. Verifique /data")
                return
            self.redirect("/")
            return
        ip = self.client_address[0]
        now = time.monotonic()
        ATTEMPTS[ip] = [t for t in ATTEMPTS[ip] if now-t < 900]
        if len(ATTEMPTS[ip]) >= 5:
            self.respond(429, layout("<main class='wrap'><p>Tentativas excedidas. Aguarde 15 minutos.</p></main>"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > 1024:
            self.respond(400, "Requisição inválida")
            return
        form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        password = form.get("password", [""])[0]
        if not password_ok(password):
            ATTEMPTS[ip].append(now)
            self.login(error="1")
            return
        ATTEMPTS.pop(ip, None)
        token = session_token()
        self.redirect("/", COOKIE_NAME + "=" + token + "; Path=/; Max-Age=28800; HttpOnly; Secure; SameSite=Strict")

if __name__ == "__main__":
    if not PASSWORD_HASH or len(SESSION_SECRET) < 32:
        raise SystemExit("Configure DASHBOARD_PASSWORD_HASH e DASHBOARD_SESSION_SECRET.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
