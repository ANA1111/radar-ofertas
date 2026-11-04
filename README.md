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
