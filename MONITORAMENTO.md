# Monitor de preços — etapa experimental

**Não busca lojas automaticamente e não publica no Telegram.** Esta etapa aceita apenas um CSV local, guarda histórico em SQLite e sinaliza quedas de preço em relação à observação anterior.

Campos obrigatórios: `source,product_id,title,url,price_brl`. Use URLs HTTPS reais e fontes autorizadas quando passar para dados de produção.

## Teste no servidor (sem rede, sem Telegram)
```bash
cd ~/radar-ofertas
git pull --ff-only
docker build -t radar-ofertas:teste .
docker run --rm --network none --entrypoint python radar-ofertas:teste monitor.py --csv samples/ofertas-exemplo.csv --db /tmp/ofertas.sqlite3
```
A primeira importação cria a linha de base, sem candidatas. O banco de exemplo em /tmp é descartado com o contêiner. Não há envio ao Telegram.

## Próximos passos
1. Definir fontes de ofertas que permitam acesso por API/feed/afiliado.
2. Manter volume persistente para o SQLite antes de executar monitoramento periódico.
3. Adicionar validação de vendedor, estoque, frete e histórico suficiente antes de chamar algo de promoção.
4. Exigir aprovação explícita para qualquer publicação real.
