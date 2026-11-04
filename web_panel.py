"""Painel do Radar de Ofertas. Biblioteca padrão; sem coleta não autorizada."""
import datetime as dt
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import urllib.request
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from monitor import SCHEMA, import_csv
from offer_workflow import message_for
from marketplaces import connector_for, ConnectorError

DATA = Path(os.getenv("DATA_DIR", "/app/data"))
DB = DATA / "offers.sqlite3"
INBOX = DATA / "inbox"
SECRET = os.getenv("APP_SECRET", "")
ADMIN = os.getenv("ADMIN_EMAIL", "").lower().strip()
PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SEND = os.getenv("ENABLE_TELEGRAM_SEND", "false").lower() == "true"
SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
TOKEN = os.getenv("BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
INTERVAL = max(60, int(os.getenv("SCAN_SECONDS", "120")))
MIN_DROP = int(os.getenv("MIN_DROP_PERCENT", "15"))
MUTEX = threading.RLock()
ATTEMPTS = {}
CSS = """
*{box-sizing:border-box}body{margin:0;background:#0a1121;color:#ebf4ff;font:15px system-ui}
header{padding:20px max(18px,calc((100% - 1100px)/2));border-bottom:1px solid #30405a;display:flex;justify-content:space-between}
main{max-width:1100px;margin:30px auto;padding:0 18px}h1{font-size:clamp(27px,4vw,42px)}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.card{background:#152139;border:1px solid #30405a;border-radius:15px;padding:20px;margin:14px 0}
.metric b{display:block;font-size:32px;margin-top:10px}small,p.muted{color:#aab8d3}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #30405a;text-align:left;padding:12px;vertical-align:top}
th{color:#aab8d3;font-size:12px}button,.button{background:#55dcbb;color:#092e28;border:0;border-radius:8px;padding:9px 12px;font-weight:bold;cursor:pointer;display:inline-block;text-decoration:none}
.danger{background:#ed9da1;color:#401217}.secondary{background:#4b5d7b;color:white}
input{background:#0a1121;color:white;border:1px solid #526682;border-radius:8px;padding:10px;max-width:100%}
form{display:inline-block;margin:3px}.scroll{overflow-x:auto}.notice{border-left:3px solid #55dcbb;padding:14px;background:#1c3544}
@media(max-width:750px){.grid{grid-template-columns:repeat(2,1fr)}td{min-width:110px}}
"""

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def db():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(candidate_id INTEGER PRIMARY KEY,state TEXT NOT NULL,scheduled_at TEXT NOT NULL,message_id TEXT);
    CREATE TABLE IF NOT EXISTS imported_files(sha TEXT PRIMARY KEY,name TEXT NOT NULL,at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,candidate_id INTEGER,action TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS clicks(id INTEGER PRIMARY KEY,at TEXT NOT NULL,candidate_id INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS affiliate_links(candidate_id INTEGER NOT NULL,channel TEXT NOT NULL,url TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(candidate_id,channel));
    """)
    return c

def sign(value):
    return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

def session():
    raw = f"{int(time.time())}.{secrets.token_urlsafe(24)}"
    return raw + "." + sign(raw)

def verified(value):
    try:
        tick, nonce, mac = value.split(".", 2)
        return 0 <= time.time()-int(tick) <= 43200 and hmac.compare_digest(mac, sign(tick+"."+nonce))
    except (ValueError, AttributeError):
        return False

def esc(value):
    return html.escape(str(value), quote=True)

def log(c, cid, action):
    c.execute("INSERT INTO audit(at,candidate_id,action) VALUES(?,?,?)", (stamp(),cid,action))

def saved_link(c, cid):
    r=c.execute("SELECT url FROM affiliate_links WHERE candidate_id=? AND channel='telegram'",(cid,)).fetchone()
    return r["url"] if r else None

def generate_link(cid):
    """Uses only the signed Shopee API and stores the result; never publishes."""
    with MUTEX:
        c=db()
        try:
            r=c.execute("SELECT rowid AS id,* FROM candidates WHERE rowid=?",(cid,)).fetchone()
            if not r or r["source"]!="SHOPEE" or r["status"] not in ("pending_review","approved"):
                raise ValueError("Oferta indisponível para conversão")
            cached=saved_link(c,cid)
            if cached: return cached
            origin=r["url"]
        finally:
            c.close()
    link=connector_for("SHOPEE").convert(origin,"telegram")
    with MUTEX:
        c=db()
        try:
            c.execute("INSERT OR IGNORE INTO affiliate_links VALUES(?,?,?,?)",(cid,"telegram",link,stamp()))
            log(c,cid,"affiliate_generated")
            c.commit()
            return saved_link(c,cid)
        finally:
            c.close()

def delivered_text(row, affiliate_url):
    # message_for validates the source and the actual observed price drop.
    return message_for(row).replace(row["url"],affiliate_url)

def deliver(cid):
    """Fail closed on ambiguous Telegram errors: never retry automatically."""
    with MUTEX:
        c = db()
        try:
            r = c.execute("SELECT rowid AS id,* FROM candidates WHERE rowid=?", (cid,)).fetchone()
            j = c.execute("SELECT * FROM jobs WHERE candidate_id=?", (cid,)).fetchone()
            if not r or r["status"] != "approved" or not j or j["state"] != "queued":
                return
            link=saved_link(c,cid)
            if not link:
                return
            text = delivered_text(r,link)
            if not SEND or not TOKEN or not CHAT:
                return
            c.execute("UPDATE jobs SET state='sending' WHERE candidate_id=?", (cid,))
            log(c,cid,"sending")
            c.commit()
        finally:
            c.close()
    try:
        payload = json.dumps({"chat_id":CHAT,"text":text}).encode()
        request = urllib.request.Request("https://api.telegram.org/bot"+TOKEN+"/sendMessage",data=payload,headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(request,timeout=18) as response:
            answer = json.load(response)
        if not answer.get("ok"):
            raise ValueError("Telegram not confirmed")
        message_id = str(answer.get("result",{}).get("message_id",""))
    except Exception:
        with MUTEX:
            c = db()
            c.execute("UPDATE jobs SET state='uncertain' WHERE candidate_id=?", (cid,))
            log(c,cid,"uncertain")
            c.commit()
            c.close()
        return
    with MUTEX:
        c=db()
        c.execute("UPDATE jobs SET state='sent',message_id=? WHERE candidate_id=?", (message_id,cid))
        c.execute("UPDATE candidates SET status='published' WHERE rowid=?", (cid,))
        log(c,cid,"published")
        c.commit()
        c.close()

def worker():
    while True:
        try:
            for file in sorted(INBOX.glob("*.csv")):
                if file.is_symlink() or not file.is_file() or file.stat().st_size > 5000000:
                    continue
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
                c=db()
                known=c.execute("SELECT 1 FROM imported_files WHERE sha=?", (digest,)).fetchone()
                c.close()
                if known:
                    file.rename(file.with_suffix(".processed"))
                    continue
                working=file.with_suffix(".processing")
                file.rename(working)
                try:
                    import_csv(str(working),str(DB),MIN_DROP)
                    c=db()
                    c.execute("INSERT OR IGNORE INTO imported_files VALUES(?,?,?)",(digest,file.name,stamp()))
                    log(c,None,"csv_import")
                    c.commit()
                    c.close()
                    working.rename(file.with_suffix(".processed"))
                except Exception:
                    working.rename(file.with_suffix(".failed"))
            # Convert small batches automatically, if the official affiliate API is enabled.
            if os.getenv("AUTO_GENERATE_LINKS","false").lower()=="true":
                c=db()
                pending=[r["id"] for r in c.execute("""
                    SELECT c.rowid AS id FROM candidates c LEFT JOIN affiliate_links a
                    ON a.candidate_id=c.rowid AND a.channel='telegram'
                    WHERE c.source='SHOPEE' AND c.status IN ('pending_review','approved')
                    AND a.candidate_id IS NULL ORDER BY c.observed_at DESC LIMIT 5
                """)]
                c.close()
                for cid in pending:
                    try: generate_link(cid)
                    except (ConnectorError,ValueError) as e:
                        print("Link conversion not available:",str(e),flush=True)
                        break
            if SEND:
                c=db()
                due=[r["candidate_id"] for r in c.execute("SELECT candidate_id FROM jobs WHERE state='queued' AND scheduled_at<=? LIMIT 8",(stamp(),))]
                c.close()
                for cid in due:
                    deliver(cid)
        except Exception as err:
            print("Worker cycle error:",type(err).__name__,flush=True)
        time.sleep(INTERVAL)

class Panel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def respond(self, text, code=200, more=None):
        self.send_response(code)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        for k,v in (more or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(text.encode())
    def redirect(self, path, more=None):
        self.respond("",303,{"Location":path,**(more or {})})
    def user(self):
        try:
            jar=cookies.SimpleCookie()
            jar.load(self.headers.get("Cookie",""))
            t=jar["radar_session"].value
            return t if verified(t) else None
        except (KeyError,cookies.CookieError):
            return None
    def layout(self, body, t=None):
        exit_form=(f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{sign("csrf:"+t)}"><button class="secondary">Sair</button></form>' if t else "")
        return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Radar de Ofertas</title><style>'+CSS+'</style></head><body><header><strong>📡 RADAR DE OFERTAS 2.0</strong>'+exit_form+'</header>'+body+'</body></html>'
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/assets/cover.svg":
            cover=Path(__file__).parent/"assets"/"cover.svg"
            if not cover.is_file():
                return self.respond("Capa indisponível",404)
            self.send_response(200)
            self.send_header("Content-Type","image/svg+xml")
            self.send_header("Cache-Control","public, max-age=3600")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'none'; style-src 'unsafe-inline'; sandbox")
            self.end_headers()
            self.wfile.write(cover.read_bytes())
            return
        if path=="/healthz":
            return self.respond("ok")
        if path.startswith("/r/"):
            return self.click(path)
        t=self.user()
        if not t:
            return self.respond(self.layout('<main><section class="card" style="max-width:550px;margin:6vh auto"><img src="/assets/cover.svg" alt="Radar de Ofertas" style="display:block;width:100%;border-radius:12px"><h1>Acesso administrativo</h1><form method="post" action="/login"><p>E-mail</p><input name="email" type="email" required autocomplete="username"><p>Senha</p><input name="password" type="password" required autocomplete="current-password"><p><button>Acessar</button></p></form></section></main>'))
        if path=="/":
            return self.home(t)
        if path.startswith("/preview/"):
            try:
                cid=int(path.rsplit("/",1)[-1])
                c=db()
                r=c.execute("SELECT rowid AS id,* FROM candidates WHERE rowid=?",(cid,)).fetchone()
                c.close()
                if r is None:
                    raise ValueError()
                return self.respond(self.layout('<main><a href="/">← Voltar</a><div class="card"><h2>Prévia da publicação</h2><pre style="white-space:pre-wrap">'+esc(message_for(r))+'</pre></div></main>',t))
            except ValueError:
                return self.respond("Oferta não encontrada",404)
        return self.respond("Não encontrado",404)
    def click(self,path):
        try:
            _,_,raw,signature=path.split("/")
            cid=int(raw)
            if not hmac.compare_digest(signature,sign("click:"+str(cid))[:24]):
                raise ValueError()
            c=db()
            r=c.execute("SELECT url,status FROM candidates WHERE rowid=?",(cid,)).fetchone()
            if not r or r["status"]!="published":
                raise ValueError()
            from offer_workflow import valid_shopee_link
            if not valid_shopee_link(r["url"]):
                raise ValueError()
            c.execute("INSERT INTO clicks(at,candidate_id) VALUES(?,?)",(stamp(),cid))
            c.commit()
            c.close()
            return self.redirect(r["url"])
        except (ValueError,TypeError):
            return self.respond("Link indisponível",404)
    def home(self,t):
        c=db()
        counts={status:c.execute("SELECT COUNT(*) n FROM candidates WHERE status=?",(status,)).fetchone()["n"] for status in ("pending_review","approved","published")}
        counts["clicks"]=c.execute("SELECT COUNT(*) n FROM clicks").fetchone()["n"]
        rows=c.execute("SELECT rowid AS id,* FROM candidates ORDER BY observed_at DESC LIMIT 80").fetchall()
        jobs={r["candidate_id"]:r["state"] for r in c.execute("SELECT candidate_id,state FROM jobs")}
        c.close()
        blocks=''.join(f'<div class="card metric"><small>{label}</small><b>{counts[key]}</b></div>' for key,label in (("pending_review","Para aprovar"),("approved","Aprovadas"),("published","Publicadas"),("clicks","Cliques medidos")))
        body='<main><img src="/assets/cover.svg" alt="Radar de Ofertas: identidade visual" style="display:block;width:100%;border-radius:18px;margin-bottom:20px"><small>Central de gestão</small><h1>Encontre, aprove e publique.</h1><div class="grid">'+blocks+'</div>'
        body+=('<p class="notice">Telegram: '+('habilitado' if SEND and TOKEN and CHAT else 'desabilitado (modo seguro)')+'. O sistema lê arquivos CSV autorizados de /app/data/inbox a cada '+str(INTERVAL)+' segundos. Nenhuma descoberta online não autorizada.</p>')
        body+='<div class="card"><h2>Automação gratuita</h2><p>A cada '+str(INTERVAL)+' segundos: importa novas observações de CSV autorizado, tenta gerar links de afiliado Shopee se a API estiver habilitada e envia ao Telegram somente ofertas aprovadas e agendadas. WhatsApp e outros marketplaces permanecem desligados.</p></div>'
        body+='<div class="card"><h2>Fila de ofertas</h2><p class="muted">O campo de data usa UTC; vazio = próxima verificação. Preço anterior = observação anterior no seu banco, não preço original do lojista.</p><div class="scroll"><table><tr><th>Produto</th><th>Preço / queda</th><th>Status</th><th>Operações</th></tr>'
        for r in rows:
            cid=r["id"]
            pct=round((r["previous_cents"]-r["price_cents"])*100/r["previous_cents"]) if r["previous_cents"] else 0
            hidden=f'<input type="hidden" name="csrf" value="{sign("csrf:"+t)}"><input type="hidden" name="id" value="{cid}">'
            actions=f'<a href="/preview/{cid}" class="button secondary">Prévia</a> '
            if r["source"]=="SHOPEE" and r["status"] in ("pending_review","approved"):
                actions+=f'<form method="post" action="/action">{hidden}<button name="action" value="generate_link" class="secondary">Gerar afiliado</button></form>'
            if r["status"]=="pending_review":
                actions+=f'<form action="/action" method="post">{hidden}<button name="action" value="approve">Aprovar</button> <button name="action" value="reject" class="danger">Rejeitar</button></form>'
            elif r["status"]=="approved" and cid not in jobs:
                actions+=f'<form action="/action" method="post">{hidden}<input name="schedule" type="datetime-local" aria-label="Agendar em UTC"><button name="action" value="queue">Agendar / enviar</button></form>'
            elif cid in jobs:
                actions+='Envio: '+esc(jobs[cid])
            if r["status"]=="published":
                actions+=f' <a class="button secondary" href="/r/{cid}/{sign("click:"+str(cid))[:24]}">Link rastreado</a>'
            body+=f'<tr><td><b>{esc(r["title"][:120])}</b><br><small>{esc(r["source"])} / {esc(r["product_id"])}</small></td><td>R$ {r["price_cents"]/100:.2f}<br><small>Queda observada: {pct}%</small></td><td>{esc(r["status"])}</td><td>{actions}</td></tr>'
        body+='</table></div></div><div class="card"><h2>Inteligência comercial</h2><p>Cliques mensurados por links rastreados. Vendas e comissões só podem ser exibidas após integração com dados reais da plataforma de afiliados.</p></div></main>'
        return self.respond(self.layout(body,t))
    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length",0))
            if not 0<=length<=16000:
                raise ValueError()
            form={k:v[0] for k,v in parse_qs(self.rfile.read(length).decode(),keep_blank_values=True).items()}
        except (ValueError,UnicodeDecodeError):
            return self.respond("Requisição inválida",400)
        path=urlparse(self.path).path
        if path=="/login":
            ip=self.client_address[0]
            recent=[x for x in ATTEMPTS.get(ip,[]) if time.monotonic()-x<600]
            if len(recent)>=8:
                return self.respond("Muitas tentativas",429)
            correct_mail=hmac.compare_digest(form.get("email","").lower().strip(),ADMIN)
            a=hashlib.pbkdf2_hmac("sha256",form.get("password","").encode(),SECRET.encode(),210000)
            b=hashlib.pbkdf2_hmac("sha256",PASSWORD.encode(),SECRET.encode(),210000)
            if correct_mail and hmac.compare_digest(a,b):
                ATTEMPTS.pop(ip,None)
                return self.redirect("/",{"Set-Cookie":"radar_session="+session()+"; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200"+("; Secure" if SECURE else "")})
            ATTEMPTS[ip]=recent+[time.monotonic()]
            return self.respond("Credenciais inválidas",401)
        t=self.user()
        if not t:
            return self.respond("Sessão inválida",401)
        if not hmac.compare_digest(form.get("csrf",""),sign("csrf:"+t)):
            return self.respond("CSRF inválido",403)
        if path=="/logout":
            return self.redirect("/",{"Set-Cookie":"radar_session=; Path=/; HttpOnly; Max-Age=0; SameSite=Strict"})
        if path!="/action":
            return self.respond("Não encontrado",404)
        try:
            cid=int(form.get("id","0"))
            action=form.get("action")
            if cid<1 or action not in ("approve","reject","queue","generate_link"):
                raise ValueError("Parâmetros inválidos")
            if action=="generate_link":
                try:
                    generate_link(cid)
                    return self.redirect("/")
                except (ConnectorError,ValueError) as exc:
                    return self.respond(self.layout('<main><h2>Link não gerado</h2><p>'+esc(exc)+'</p><a href="/">Voltar</a></main>',t),400)
            with MUTEX:
                c=db()
                r=c.execute("SELECT rowid AS id,* FROM candidates WHERE rowid=?",(cid,)).fetchone()
                if not r:
                    raise ValueError("Oferta não encontrada")
                if action in ("approve","reject"):
                    if r["status"]!="pending_review":
                        raise ValueError("Oferta já revisada")
                    status="approved" if action=="approve" else "rejected"
                    c.execute("UPDATE candidates SET status=? WHERE rowid=?",(status,cid))
                    log(c,cid,status)
                else:
                    if r["status"]!="approved" or c.execute("SELECT 1 FROM jobs WHERE candidate_id=?",(cid,)).fetchone():
                        raise ValueError("Oferta não elegível")
                    message_for(r)
                    if not saved_link(c,cid):
                        raise ValueError("Gere o link de afiliado antes de agendar o Telegram")
                    raw=form.get("schedule","").strip()
                    when=dt.datetime.fromisoformat(raw).replace(tzinfo=dt.timezone.utc) if raw else dt.datetime.now(dt.timezone.utc)
                    if when>dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=30):
                        raise ValueError("Máximo de 30 dias")
                    c.execute("INSERT INTO jobs(candidate_id,state,scheduled_at) VALUES(?,?,?)",(cid,"queued",when.isoformat()))
                    log(c,cid,"queued")
                c.commit()
                c.close()
            return self.redirect("/")
        except (ValueError,OverflowError) as exc:
            return self.respond(self.layout('<main><h2>Operação não concluída</h2><p>'+esc(exc)+'</p><a href="/">Voltar</a></main>',t),400)

def main():
    if len(SECRET)<32 or len(PASSWORD)<14 or not ADMIN:
        raise SystemExit("Configure APP_SECRET (32+), ADMIN_EMAIL e ADMIN_PASSWORD (14+)")
    if not 1<=MIN_DROP<=99:
        raise SystemExit("MIN_DROP_PERCENT inválido")
    DATA.mkdir(parents=True,exist_ok=True)
    INBOX.mkdir(exist_ok=True)
    db().close()
    threading.Thread(target=worker,daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","8080"))),Panel).serve_forever()

if __name__=="__main__":
    main()
