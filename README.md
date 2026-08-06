# AI News Radar

Digest diário de **lançamentos de produtos de AI e automação**, entregue no Telegram.
Corre no GitHub Actions, sem servidor e sem custos.

## Como funciona

```
Recolha  ->  Deduplicação  ->  Scoring  ->  Refinamento LLM  ->  Telegram
```

1. **Recolha** — 20 feeds RSS, Hacker News, releases de GitHub e pesquisas no Google News
   (para empresas sem RSS, como a Anthropic).
2. **Deduplicação** — a mesma história aparece em vários sites; é colapsada por
   semelhança de títulos e por URL canónico.
3. **Scoring** — heurística que privilegia sinais de lançamento (*launches*,
   *introducing*, *now available*) e penaliza ruído (opinião, notícias de pessoas,
   financiamento, tutoriais).
4. **Refinamento LLM** — os melhores candidatos são reavaliados e resumidos numa
   frase em português. **Opcional**: sem chave de API, o resto funciona na mesma.
5. **Telegram** — envio formatado, no máximo 6 notícias por digest.

Nada é enviado duas vezes: o `state.json` guarda o que já saiu nos últimos 21 dias.

## Configuração

### Secrets do repositório

`Settings` → `Secrets and variables` → `Actions`

| Secret | Onde obter |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | [@userinfobot](https://t.me/userinfobot) → `/start` |
| `LLM_API_KEY` | [Google AI Studio](https://aistudio.google.com) ou [Groq](https://console.groq.com) |

### Variables opcionais

| Variable | Omissão | Notas |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` ou `groq` |
| `LLM_MODEL` | `gemini-2.0-flash` | Só se quiseres outro modelo |

> Antes do primeiro envio, abre uma conversa com o teu bot e manda `/start`.
> O Telegram bloqueia bots que tentem escrever a quem nunca os contactou.

## Ajustar sem tocar no código

Tudo o que importa está no `fontes.yaml`: feeds e respetivos pesos, palavras-chave
de lançamento e de ruído, número de notícias por digest e score mínimo.

Se um digest vier fraco, sobe o `score_minimo`. Se vier vazio demais, desce-o.

## Correr localmente

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# mostra o digest sem enviar nada nem gravar estado
.venv/bin/python -m src.main --seco --verboso
```

Para testar o envio real, copia `.env.example` para `.env`, preenche, e exporta as
variáveis antes de correr sem `--seco`.

## Horário

O cron do GitHub corre em UTC: **07:30** e **17:30**.

Em Portugal isso dá 08:30/18:30 no horário de verão e 07:30/17:30 no de inverno.
O GitHub também pode atrasar execuções agendadas em alturas de pico — normal, e
irrelevante para um digest.

Podes forçar uma execução a qualquer momento em `Actions` → `Digest` → `Run workflow`,
com a opção de modo seco para veres o resultado sem receber notificação.
