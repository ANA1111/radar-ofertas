"""Radar de Ofertas: painel somente leitura, sem dependências externas."""
import base64
import hashlib
import hmac
import html
import json
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
.logout{background:transparent;border:1px solid #52627c;color:white;padding:9px 13px}
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
        self.send_header("Referrer-Policy", "no-referrer")
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
                + notice + "<div class='grid'>" + cards + "</div>"
                "<section class='card section'><h2>Últimas oportunidades</h2><div class='scroll'>"
                "<table><thead><tr><th>Produto</th><th>Preço</th><th>Anterior</th><th>Status</th><th>Data (UTC)</th></tr></thead>"
                "<tbody>" + rows + "</tbody></table></div></section>"
                "<section class='section notice'>🔒 Painel somente leitura. Nenhum botão envia ofertas ou executa automações.</section></main>")
        self.respond(200, layout(body))

    def do_POST(self):
        if self.path not in ("/login","/logout"):
            self.respond(404, "Página não encontrada")
            return
        # Bloqueia requisições de origem cruzada; proxy deve preservar Host.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        # PUBLIC_ORIGIN define a origem externa confiável atrás do proxy HTTPS.
        # Nunca confiar em X-Forwarded-Host fornecido por clientes.
        public_origin = os.environ.get("DASHBOARD_PUBLIC_ORIGIN", "").rstrip("/")
        expected_origin = public_origin or ("https://" + host)
        if origin and origin != expected_origin:
            self.respond(403, "Origem não permitida")
            return
        if self.path == "/logout":
            self.redirect("/", COOKIE_NAME + "=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict")
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
