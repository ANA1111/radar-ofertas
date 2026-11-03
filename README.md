# Radar de Ofertas

Projeto experimental de monitoramento de promoções e publicação no Telegram.

## Segurança
- O modo padrão é **dry-run** e não publica mensagens.
- Nunca faça commit de tokens, senhas ou arquivos .env.
- Configure credenciais somente nas variáveis de ambiente do Easypanel.
- Não há monitoramento de ofertas nem disparos automáticos nesta versão.

## Easypanel
1. Crie projeto `radar-ofertas` e serviço App `telegram-bot`.
2. Conecte este repositório na branch `main`.
3. Selecione Dockerfile, caminho `Dockerfile`, contexto `/`.
4. Não configure domínio nem portas públicas.
5. Faça Deploy. O container executa `python -u app.py dry-run` e encerra após imprimir `DRY RUN OK`. Esse encerramento é esperado.
6. Somente após testar, configure BOT_TOKEN e TEST_CHAT_ID no painel. O envio técnico exige comando `python -u app.py test-send` e ALLOW_TEST_SEND=true.

## Limites
Esta versão não consulta preços nem cria links de afiliados. O envio técnico é apenas para um canal privado de testes.
