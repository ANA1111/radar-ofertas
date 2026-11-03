"""Radar de Ofertas: teste seguro de inicialização e Telegram."""
import os
import sys
import json
import urllib.request

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    if mode == "dry-run":
        print("DRY RUN OK: Radar de Ofertas iniciado. Nenhuma mensagem enviada.", flush=True)
        return
    if mode != "test-send":
        raise SystemExit("Modo inválido. Use dry-run ou test-send.")
    if os.getenv("ALLOW_TEST_SEND") != "true":
        raise SystemExit("Envio bloqueado: ALLOW_TEST_SEND não está true.")
    token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TEST_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("BOT_TOKEN e TEST_CHAT_ID são necessários.")
    data = json.dumps({"chat_id": chat_id, "text": "🧪 Teste técnico do Radar de Ofertas. Nenhuma promoção real."}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise SystemExit("Telegram não confirmou o teste.")
    print("Mensagem técnica enviada ao canal privado de testes.", flush=True)

if __name__ == "__main__":
    main()
