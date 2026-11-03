# Painel Radar de Ofertas — implantação segura

Painel responsivo, em português, somente leitura do SQLite. Não envia ofertas, não acessa Shopee e não exige serviços pagos. O login usa PBKDF2-HMAC-SHA256 e cookie assinado, HttpOnly, Secure, SameSite=Strict (8h). A proteção de tentativas é em memória, por IP, e não substitui controles de borda.

## 1. Criar senha e segredo (na VPS)
Não publique nem compartilhe esses valores. A senha deve ser longa e única.

```bash
cd ~/radar-ofertas
read -r -s -p "Crie a senha do painel: " RADAR_PASSWORD; echo
export RADAR_PASSWORD
python3 - <<'PY'
import os,hashlib,secrets
password=os.environ["RADAR_PASSWORD"]
salt=secrets.token_bytes(16)
rounds=310000
digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,rounds)
print("DASHBOARD_PASSWORD_HASH=pbkdf2_sha256$%s$%s$%s"%(rounds,salt.hex(),digest.hex()))
print("DASHBOARD_SESSION_SECRET="+secrets.token_hex(32))
PY
unset RADAR_PASSWORD
```

Guarde as duas variáveis geradas **apenas** nas variáveis de ambiente/segredos do Easypanel, nunca no GitHub, em screenshots ou em mensagens.

## 2. Easypanel
- Crie um novo serviço **App** no projeto existente, a partir do repositório GitHub `ANA1111/radar-ofertas`, branch `main`.
- Build Dockerfile: `Dockerfile.dashboard`. Porta interna: `8080`.
- Defina `DASHBOARD_PASSWORD_HASH`, `DASHBOARD_SESSION_SECRET`, `RADAR_DB=/data/ofertas.sqlite3`, `PORT=8080`.
- **Volume de leitura**: disponibilize o arquivo da VPS `/root/radar-ofertas/data/ofertas.sqlite3` no contêiner em `/data/ofertas.sqlite3`, **somente leitura**. Confirme o caminho absoluto com `realpath ~/radar-ofertas/data/ofertas.sqlite3`. O modo de configuração de volumes depende da versão do Easypanel; não monte o diretório inteiro da aplicação nem exponha o banco publicamente. Se o Easypanel não oferecer bind mount somente leitura, pare antes de publicar e escolha uma implantação Docker Compose separada com volume `:ro`.
- Configure o domínio `ofertas.gestoncuid.tech` e HTTPS/TLS no proxy Easypanel. No DNS do domínio, crie registro A `ofertas` apontando para o IP público da VPS (ou o registro que seu provedor orientar). Não use `gestoncuid.tech.ofertas`.
- Exponha **somente pelo proxy HTTPS**, nunca diretamente a porta 8080 à internet. Não habilite deploy antes de configurar segredos e volume.

## 3. Verificações
- Acesse `https://ofertas.gestoncuid.tech`; deve mostrar login.
- Entre com a senha criada; o painel deve mostrar os totais reais do SQLite.
- Use 'Sair'; tente abrir o painel novamente.
- Verifique no celular.
- Nunca compartilhe a senha, hash, segredo ou tokens em capturas.

## Limites atuais
- O painel é somente leitura; não inicia ou agenda coleta e não publica promoções.
- A contagem de ofertas é do banco, não é um dado ao vivo da Shopee.
- Para produção pública, adicionar rate limiting no proxy, logs/alertas, backups e, idealmente, autenticação gerenciada ou MFA.
