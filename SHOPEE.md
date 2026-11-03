# Shopee — integração segura (fase 1)

A Shopee possui uma API oficial para afiliados, mas acesso, campos e limites dependem das credenciais e permissões da conta. **Este adaptador não consulta a Shopee.** Também não gera links, não raspa páginas e não envia Telegram.

## Arquivo de entrada
Prepare localmente um CSV UTF-8 com cabeçalho:
```csv
product_id,title,price_brl,affiliate_url
```
- `product_id`: identificador estável do produto, conferido no programa
- `title`: nome real do produto
- `price_brl`: preço efetivamente verificado em reais (ex.: 59.90)
- `affiliate_url`: URL de afiliado **gerada pelo programa oficial** e apontando para domínio Shopee aceito

O adaptador só valida o formato e o domínio. **Não prova** a legitimidade do link, preço, estoque, frete ou comissão. Confira manualmente antes de usar. O arquivo deve vir de dados que você tem permissão para utilizar.

## Execução segura sem rede
```bash
docker run --rm --network none --read-only --tmpfs /tmp \
  -v "$PWD/imports:/imports:ro" \
  --entrypoint python radar-ofertas:teste \
  shopee_import.py --input /imports/shopee.csv --output /tmp/shopee-normalizado.csv
```
O resultado é escrito apenas no contêiner efêmero e desaparece ao terminar. Para persistir, configure um volume de saída em etapa posterior.

## Próxima fase
Depois de confirmar acesso ao Portal do Afiliado e, se disponível, às credenciais oficiais da Open API brasileira, implementar cliente autenticado conforme a documentação fornecida pela própria Shopee. Não armazenar App Secret no GitHub.
