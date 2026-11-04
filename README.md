# Estufa → Power BI

Envia automaticamente as leituras dos sensores da estufa (ThingSpeak, canal 3546817) para o
**Power BI Web**, em médias de 15 minutos, a cada 15 minutos, pelo GitHub Actions.

Faz parte do projeto **Power BI Analytics** (painel em https://estufa.freedev.app).

## Como funciona

```
ThingSpeak → PHP → MySQL → PHP ─┐
                                ├─→ Power BI (modelo de streaming "Estufa_Sensores_15min")
ThingSpeak → Python (GitHub) ───┘
```

- O **site** (PHP + MySQL no InfinityFree) envia as médias calculadas no MySQL sempre que alguém abre o painel.
- Este **script Python** roda sozinho no GitHub a cada 15 minutos, mesmo sem ninguém no site.
  A hospedagem grátis bloqueia acessos que não sejam de navegador, por isso o script lê direto do ThingSpeak.
- Cada linha tem a coluna `origem` (`MySQL (site)` ou `Python (GitHub)`). As duas fontes mandam os mesmos
  blocos de 15 min, então médias, mínimos e máximos não mudam com linhas repetidas.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `enviar_powerbi.py` | Lê o ThingSpeak, agrupa em 15 min e envia ao Power BI (só biblioteca padrão do Python). |
| `.github/workflows/powerbi.yml` | Agenda a execução a cada 15 min e salva o progresso. |
| `ultimo_envio.txt` | Último bloco enviado (atualizado pelo próprio workflow). |

## Configuração

1. No Power BI Web, o modelo de streaming `Estufa_Sensores_15min` (API, com **Análise de dados histórica** ativada).
2. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Nome: `POWERBI_PUSH_URL`
   - Valor: a "URL de Push" do modelo (Power BI → ⋯ do modelo → Informações da API).
3. **Actions → Enviar para o Power BI → Run workflow** para rodar na hora (sem `ultimo_envio.txt`, ele envia todo o histórico).

Rodar no computador:

```bash
POWERBI_PUSH_URL="https://api.powerbi.com/beta/…/rows?key=…" python3 enviar_powerbi.py
```

A URL de Push tem uma chave secreta: nunca coloque ela no código, só no Secret.
