#!/usr/bin/env python3
"""
Envia as leituras dos sensores da estufa (ThingSpeak) para o Power BI, em médias de 15 minutos.

- Lê as leituras novas do canal público do ThingSpeak.
- Agrupa em blocos de 15 min (média, mínima e máxima de temperatura, umidade e pressão).
- Envia só os blocos já fechados para a "URL de Push" do modelo de streaming do Power BI.
- Guarda em ultimo_envio.txt o último bloco enviado, para não repetir na próxima execução.

Uso: POWERBI_PUSH_URL="https://api.powerbi.com/beta/.../rows?key=..." python3 enviar_powerbi.py
Só usa a biblioteca padrão do Python (3.9+).
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CANAL = os.environ.get("THINGSPEAK_CHANNEL_ID", "3546817")
CHAVE_LEITURA = os.environ.get("THINGSPEAK_READ_KEY", "")  # vazio: canal público
FUSO = ZoneInfo("America/Sao_Paulo")
ARQUIVO_ESTADO = Path(__file__).with_name("ultimo_envio.txt")
ORIGEM = "Python (GitHub)"
BLOCO = timedelta(minutes=15)
JANELA = timedelta(hours=12)  # ~2.000 leituras por consulta; o ThingSpeak devolve no máximo 8.000
LOTE = 500                    # linhas por envio ao Power BI


def obter_json(url, tentativas=4):
    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(url, timeout=30) as resposta:
                return json.load(resposta)
        except (urllib.error.URLError, TimeoutError) as erro:
            if tentativa == tentativas - 1:
                raise
            print(f"  ThingSpeak falhou ({erro}); tentando de novo…")
            time.sleep(5 * (tentativa + 1))


def feeds(**params):
    params.update(timezone="America/Sao_Paulo")
    if CHAVE_LEITURA:
        params["api_key"] = CHAVE_LEITURA
    url = f"https://api.thingspeak.com/channels/{CANAL}/feeds.json?" + urllib.parse.urlencode(params)
    return obter_json(url)


def inicio_do_bloco(momento):
    return momento.replace(minute=momento.minute - momento.minute % 15, second=0, microsecond=0)


def numero(valor):
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def ler_estado():
    if ARQUIVO_ESTADO.exists():
        texto = ARQUIVO_ESTADO.read_text().strip()
        if texto:
            return datetime.fromisoformat(texto)
    return None


def salvar_estado(bloco):
    ARQUIVO_ESTADO.write_text(bloco.strftime("%Y-%m-%dT%H:%M:%S") + "\n")


def buscar_leituras(desde, ate):
    """Leituras com horário local (sem fuso) entre desde e ate."""
    leituras = []
    janela_inicio = desde
    while janela_inicio < ate:
        janela_fim = min(janela_inicio + JANELA, ate)
        dados = feeds(
            start=janela_inicio.strftime("%Y-%m-%d %H:%M:%S"),
            end=(janela_fim - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
            results=8000,
        )
        for item in dados.get("feeds", []):
            momento = datetime.fromisoformat(item["created_at"]).astimezone(FUSO).replace(tzinfo=None)
            if desde <= momento < ate:
                leituras.append((momento, numero(item.get("field1")), numero(item.get("field2")), numero(item.get("field3"))))
        janela_inicio = janela_fim
    return leituras


def agrupar(leituras):
    blocos = {}
    for momento, temperatura, umidade, pressao in leituras:
        b = blocos.setdefault(inicio_do_bloco(momento), {"n": 0, "t": [], "u": [], "p": []})
        b["n"] += 1
        for chave, valor in (("t", temperatura), ("u", umidade), ("p", pressao)):
            if valor is not None:
                b[chave].append(valor)

    def resumo(valores):
        if not valores:
            return None, None, None
        return round(sum(valores) / len(valores), 2), round(min(valores), 2), round(max(valores), 2)

    linhas = []
    for inicio in sorted(blocos):
        b = blocos[inicio]
        tm, tmin, tmax = resumo(b["t"])
        um, umin, umax = resumo(b["u"])
        pm, pmin, pmax = resumo(b["p"])
        linhas.append({
            "periodo": inicio.strftime("%Y-%m-%dT%H:%M:%S"),
            "temperatura_media": tm, "temperatura_min": tmin, "temperatura_max": tmax,
            "umidade_media": um, "umidade_min": umin, "umidade_max": umax,
            "pressao_media": pm, "pressao_min": pmin, "pressao_max": pmax,
            "leituras": b["n"],
            "origem": ORIGEM,
        })
    return linhas


def enviar(url, linhas, tentativas=4):
    corpo = json.dumps(linhas).encode()
    for tentativa in range(tentativas):
        pedido = urllib.request.Request(url, data=corpo, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=30):
                return
        except urllib.error.HTTPError as erro:
            # 429: limite de envios do Power BI; espera e tenta de novo.
            if erro.code in (429, 500, 502, 503, 504) and tentativa < tentativas - 1:
                time.sleep(5 * (tentativa + 1))
                continue
            detalhe = erro.read()[:200].decode(errors="replace")
            raise SystemExit(f"O Power BI recusou o envio (HTTP {erro.code}): {detalhe}")
        except (urllib.error.URLError, TimeoutError):
            if tentativa == tentativas - 1:
                raise
            time.sleep(5 * (tentativa + 1))


def main():
    url = os.environ.get("POWERBI_PUSH_URL", "").strip()
    if not url.startswith("https://api.powerbi.com/"):
        raise SystemExit("Defina POWERBI_PUSH_URL com a URL de Push do modelo de streaming do Power BI.")

    ultimo = ler_estado()
    if ultimo:
        desde = ultimo + BLOCO
    else:
        criado = feeds(results=0)["channel"]["created_at"]
        desde = inicio_do_bloco(datetime.fromisoformat(criado).astimezone(FUSO).replace(tzinfo=None))
        print(f"Primeira execução: enviando o histórico desde {desde:%d/%m/%Y %H:%M}.")
    # O bloco atual ainda está aberto; vai na próxima execução. A folga de 2 min espera leituras atrasadas.
    ate = inicio_do_bloco(datetime.now(FUSO).replace(tzinfo=None) - timedelta(minutes=2))

    if desde >= ate:
        print("Nada novo: o Power BI já está em dia.")
        return

    leituras = buscar_leituras(desde, ate)
    linhas = agrupar(leituras)
    print(f"{len(leituras)} leituras de {desde:%d/%m %H:%M} a {ate:%d/%m %H:%M} → {len(linhas)} blocos de 15 min.")

    for i in range(0, len(linhas), LOTE):
        lote = linhas[i:i + LOTE]
        enviar(url, lote)
        salvar_estado(datetime.fromisoformat(lote[-1]["periodo"]))
        print(f"  enviados {i + len(lote)}/{len(linhas)}")
        time.sleep(1)

    if not linhas:
        # Sem leituras no intervalo (sensor parado): avança mesmo assim para não reconsultar sempre o mesmo trecho.
        salvar_estado(ate - BLOCO)
    print("Concluído.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
