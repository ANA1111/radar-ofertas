# Radar de Ofertas — Telegram e Shopee (sem novos custos)

**Foco atual:** apenas Telegram e automação de ofertas da Shopee. WhatsApp, Amazon, Mercado Livre e TikTok Shop permanecem desativados. O sistema usa sua VPS existente; não há serviços pagos adicionais no código, mas a VPS continua tendo seu custo atual.

## Fluxo atualizado

1. A rotina verifica a pasta autorizada `/app/data/inbox` periodicamente e importa novos CSVs para o histórico de preços. **Ainda não existe descoberta automática na Shopee**; ela depende de uma fonte autorizada alimentando a pasta.
2. O sistema cria candidatos quando uma queda de preço é confirmada contra a observação anterior.
3. Com credenciais válidas da API Shopee Affiliate, pode converter os links do candidato para afiliados com `AUTO_GENERATE_LINKS=true`, ou você clica em **Gerar afiliado**. Sem credenciais válidas a conversão não é possível; não se fabricam links.
4. Você confere o produto e **aprova manualmente**.
5. Depois de criado um link de afiliado, pode **agendar / enviar** a oferta. A rotina publica somente os candidatos aprovados e agendados, quando `ENABLE_TELEGRAM_SEND=true`.
6. Falhas ambíguas no Telegram ficam com status `uncertain`, exigindo revisão manual; o sistema não tenta reenviar automaticamente.

**Variáveis adicionais no Easypanel:** `SHOPEE_APP_ID`, `SHOPEE_APP_SECRET` e `AUTO_GENERATE_LINKS=false` (altere para `true` depois de obter credenciais válidas e testar). `BOT_TOKEN` e `TELEGRAM_CHAT_ID` são necessários para envio. Nunca coloque segredos no GitHub.

**Teste local gratuito e offline:** `python -m unittest discover -s tests -v`. O código implementa a chamada de conversão oficial, mas seu sucesso dependerá de permissões e credenciais da Shopee. Não foi feito teste real de API ou de envio pelo Telegram nesta etapa.

**Custo zero adicional não significa integração liberada:** é necessário verificar acesso gratuito à API da sua conta de afiliado e manter o uso dentro dos limites da plataforma.

---

# Radar de Ofertas 2.0

Painel privado de triagem de ofertas, monitoramento por importação recorrente de CSV autorizado e publicação controlada no Telegram.

## Entregue

- Painel web responsivo em Python (biblioteca padrão), login de administrador, sessão assinada, cookies HttpOnly/SameSite e proteção CSRF.
- Histórico SQLite, cálculo de queda do preço observado e fila de revisão humana.
- Prévia e descrição de anúncios, aprovação/rejeição individual e agendamento em UTC.
- Publicação **somente** de ofertas aprovadas. Ativação opt-in via variável `ENABLE_TELEGRAM_SEND=true`.
- Registros de envio, estado `uncertain` em falha de rede para impedir reenvio automático potencialmente duplicado.
- Link rastreado para ofertas publicadas e contador de cliques.
- Verificação periódica da pasta `/app/data/inbox`, importação de CSV de fonte autorizada.
- Dockerfile com usuário não-root e healthcheck.

**Limitações:** não pesquisa a Shopee em tempo real, não gera automaticamente links de afiliado, não mede vendas/comissões e não publica sem aprovação. A detecção automática acontece **sobre arquivos CSV fornecidos por integração autorizada**. O preço anterior é uma observação do histórico local, não o preço de tabela da loja.

## Easypanel: implantação segura

1. Faça backup de `/app/data` se já tiver histórico do radar.
2. No serviço App, conecte `ANA1111/radar-ofertas` à branch `main`, build com Dockerfile e contexto raiz `/`.
3. Monte um volume persistente em `/app/data`; sem isso, histórico e aprovações podem sumir ao reiniciar.
4. Configure as variáveis abaixo **somente nas configurações do Easypanel**, nunca no GitHub:

```dotenv
APP_SECRET=<chave_aleatoria_de_32_ou_mais_caracteres>
ADMIN_EMAIL=<seu_email_admin>
ADMIN_PASSWORD=<senha_forte_de_14_ou_mais_caracteres>
PORT=8080
DATA_DIR=/app/data
COOKIE_SECURE=true
MIN_DROP_PERCENT=15
SCAN_SECONDS=120
ENABLE_TELEGRAM_SEND=false
BOT_TOKEN=<seu_token_telegram>
TELEGRAM_CHAT_ID=<id_do_canal_autorizado>
```

5. Configure domínio próprio no Easypanel, **HTTPS obrigatório** e encaminhamento para a porta `8080`. Não exponha esta porta diretamente à Internet; use o proxy HTTPS do painel. `COOKIE_SECURE=true` exige HTTPS para login funcionar.
6. Faça deploy e verifique `/healthz`. Entre no domínio com `ADMIN_EMAIL` e `ADMIN_PASSWORD`.
7. Envie arquivos CSV autorizados ao diretório persistente `/app/data/inbox` (via processo confiável/SFTP/volume). O serviço os importa periodicamente e renomeia arquivos consumidos como `.processed`.
8. Revise ofertas no painel e aprove apenas as desejadas. Para **liberar o envio**, configure `BOT_TOKEN` e `TELEGRAM_CHAT_ID` corretos e altere `ENABLE_TELEGRAM_SEND=true` após testar num canal de teste. O painel **nunca cria automaticamente novas aprovações**.

### Formato CSV aceito

```csv
source,product_id,title,url,price_brl
SHOPEE,sku-101,Fone Bluetooth,https://s.shopee.com.br/EXEMPLO,79.90
```

O endereço do exemplo é ilustrativo; substitua pelo seu link real e autorizado. Na primeira observação um produto é registrado sem gerar oferta. Importe outra observação com preço menor (pelo menos `MIN_DROP_PERCENT`) para criar candidato de aprovação.

## Operação

- **Fila de revisão:** aprovação manual obrigatória para cada candidato.
- **Agendamento:** campo do painel é UTC (Bahia = UTC−3, portanto 15:00 UTC corresponde a 12:00 em Salvador).
- **Publicação:** apenas jobs aprovados e agendados são executados, se `ENABLE_TELEGRAM_SEND=true`.
- **Falha de envio:** estado `uncertain` exige reconciliação manual; não há retry automático para evitar duplicatas.
- **Cliques:** só links rastreados do painel são contabilizados; o link direto publicado no Telegram **não** incrementa o contador de cliques. Não confundir com visitas/vendas reportadas pela Shopee.

## Segurança e próximos passos

Esta é uma primeira versão para **um operador** e **um processo de aplicação**. É recomendável adicionar rate limiting persistente, backup automatizado do SQLite, restrição de IP no proxy, controle de múltiplos usuários e testes integrados antes de escala. A autenticação usa credenciais por ambiente; o segredo de sessão deve ser fixo e protegido. Não altere APP_SECRET sem planejar invalidar sessões.

O painel não tem integração oficial com APIs da Shopee nesta versão. Para descoberta e dados de vendas reais, conecte somente fonte/API autorizada e verifique termos da plataforma.


## Identidade visual e histórico de commits

A capa vetorial do Radar de Ofertas fica em `assets/cover.svg`, é carregada na tela de login e no painel após autenticação. Ela não depende de serviços externos nem incorpora scripts. Os commits de alteração foram separados por intenção: `feat(brand)`, `feat(ui)`, `fix(deploy)` e `feat(auth-ui)`. A partir daqui, cada alteração deverá ter commit com escopo e descrição claros.

## Segurança de alterações

- Nunca inclua credenciais em arquivos versionados nem na capa.
- Mantenha `ENABLE_TELEGRAM_SEND=false` até passar por teste de integração e validação do administrador.
- Use HTTPS no proxy reverso e mantenha `COOKIE_SECURE=true`.
- Configure volume persistente e backup externo de `/app/data`.
- Não misture alterações de design com ativação de disparos, mudanças de banco ou integrações sem testes.
- Revise a configuração do Easypanel após cada deploy; atualizar o repositório **não significa** que a VPS foi atualizada automaticamente.
- O conector Shopee inicial em `marketplaces.py` requer credenciais oficiais e ainda não está conectado ao fluxo completo do painel.

## Diagnóstico: Easypanel continua mostrando painel antigo

Em 2026-11-04 o build legado `Dockerfile.dashboard` foi atualizado para iniciar `web_panel.py` (mesma aplicação do `Dockerfile`). Um novo build desse commit ou mais recente não deve exibir o antigo formulário "Cadastrar oferta Shopee".

1. Em **Source**, confirme o repositório `ANA1111/radar-ofertas` e a branch `main`.
2. Em **Build**, use `Dockerfile.dashboard` ou `Dockerfile`; ambos agora iniciam `web_panel.py`.
3. Configure antes do deploy: `APP_SECRET` (32+ caracteres), `ADMIN_EMAIL`, `ADMIN_PASSWORD` (14+ caracteres), `COOKIE_SECURE=true`, e mantenha `ENABLE_TELEGRAM_SEND=false`.
4. **Faça backup dos bancos e volumes antes de trocar a imagem.** O painel anterior usava `RADAR_DB=/data/ofertas.sqlite3`; o novo build legado usa `DATA_DIR=/data` e cria `/data/offers.sqlite3`. O novo banco NÃO importa automaticamente o banco antigo. Não apague `/data/ofertas.sqlite3` nem volumes associados.
5. Na aba de implantações, execute novo build e verifique o commit efetivamente construído, os logs da aplicação e a saúde do container. Se a página antiga continuar, verifique qual serviço é destino da rota de domínio no Easypanel.
6. O serviço novo exige suas próprias credenciais de login; `DASHBOARD_PASSWORD_HASH` e `DASHBOARD_SESSION_SECRET` do painel anterior não substituem as variáveis novas. Não compartilhe prints de segredos.
7. Se a nova tela aparecer sem os registros antigos, **não exclua nada**: será necessária uma migração planejada com cópia de segurança.

A publicação no Telegram permanece desativada por padrão; não habilite antes de confirmar o canal de testes e testar aprovações.
