# Radar de Ofertas

Monitor offline de preços observados, triagem de oportunidades e publicação **manual** em canal privado de teste no Telegram.

## O que funciona
- Importar CSV autorizado da Shopee com `shopee_import.py`
- Registrar histórico de preços e criar candidatos quando houver queda real observada com `monitor.py`
- Listar, pré-visualizar, aprovar ou rejeitar candidatos com `offer_workflow.py`
- Criar descrição de oferta com valor observado, queda calculada, URL fornecida e aviso de afiliado
- Publicar apenas ofertas aprovadas, no `TEST_CHAT_ID`, com `ALLOW_TEST_SEND=true`
- Bloquear reenvio de candidatos marcados como publicados (exceto em falhas entre envio e gravação, que ainda exigem reconciliação)

## Limites
**Ainda não é um radar automático online.** Não busca Shopee, não apura comissão, não cria link afiliado, não roda jobs periódicos e não possui interface web. A referência de 'preço anterior' é a última observação salva no banco local, **não** preço original anunciado pelo lojista. Não há garantia de disponibilidade ou validade do preço.

## Segurança
- O padrão do serviço é `dry-run`: não publica nenhuma mensagem.
- Não armazene token ou segredo em commit; configure-os no Easypanel.
- A aplicação só publica no chat definido em `TEST_CHAT_ID`, com consentimento explícito por candidato.
- Nunca compartilhe tokens em mensagens ou prints.
- Para persistir histórico, monte volume do Easypanel em `/app/data`.

## Easypanel
1. Serviço conectado ao repositório e branch `main` usando Dockerfile e contexto `/`.
2. Adicione volume persistente em `/app/data`.
3. Não exponha portas nem domínio; o container não é um servidor web.
4. Faça Deploy. A execução padrão `python -u app.py dry-run` termina com `DRY RUN OK`. **O encerramento é esperado.**
5. Para execução manual, abra o terminal do serviço. Caso o serviço pare rapidamente, use uma tarefa/execução separada com a mesma imagem e volume montado.
6. Configure `BOT_TOKEN`, `TEST_CHAT_ID` e `ALLOW_TEST_SEND=true` somente para testes de publicação.

## Exemplo de fluxo (terminal)
```bash
python shopee_import.py --input samples/shopee_input.csv --output data/normalized.csv
python monitor.py --csv data/normalized.csv --db data/offers.sqlite3
# Uma segunda importação com um preço menor para o mesmo product_id cria candidatos.
python offer_workflow.py list
python offer_workflow.py preview --id 1
python offer_workflow.py approve --id 1
python offer_workflow.py publish --id 1
```

A importação apenas prepara ofertas fornecidas pelo operador; não consulta preços em tempo real.
