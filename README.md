# AI News Radar

Digest diário de **lançamentos de produtos de AI e automação**, entregue por email.
Corre no GitHub Actions, sem servidor e sem custos.

## Como funciona

```
Recolha  ->  Deduplicação  ->  Scoring  ->  Refinamento LLM  ->  Email
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
5. **Email** — HTML formatado via SMTP do Gmail, no máximo 6 notícias por digest.

Nada é enviado duas vezes: o `state.json` guarda o que já saiu nos últimos 21 dias.

## Configuração

### Secrets do repositório

`Settings` → `Secrets and variables` → `Actions`

| Secret | Onde obter |
|---|---|
| `SMTP_UTILIZADOR` | A tua conta Gmail, ex. `nome@gmail.com` |
| `SMTP_PASSWORD` | [App Password](https://myaccount.google.com/apppasswords) de 16 caracteres |
| `EMAIL_DESTINO` | Endereço que recebe o digest |
| `LLM_API_KEY` | [Google AI Studio](https://aistudio.google.com) ou [Groq](https://console.groq.com) |

### Variables opcionais

| Variable | Omissão | Notas |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` ou `groq` |
| `LLM_MODEL` | `gemini-2.0-flash` | Só se quiseres outro modelo |

> `SMTP_PASSWORD` **não é a password da tua conta Google** — tem de ser uma App
> Password. Exige 2-Step Verification activa. Se puseres a password normal, o
> Gmail devolve `535 Authentication failed`.

> O `EMAIL_DESTINO` é um Secret, e não configuração no `fontes.yaml`, porque este
> repositório é público — um endereço em texto simples seria recolhido por bots.

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

**Todos os dias às 9h de Lisboa**, durante todo o ano.

O cron do GitHub só entende UTC e não conhece o horário de verão. Por isso são
agendadas duas execuções — 08:00 e 09:00 UTC — e o `--so-as 9` deixa passar apenas
aquela que calha às 9h em `Europe/Lisbon`. A outra sai em segundos sem fazer nada.

|  | 08:00 UTC | 09:00 UTC |
|---|---|---|
| Inverno (WET) | 08h — ignora | **09h — envia** |
| Verão (WEST) | **09h — envia** | 10h — ignora |

O GitHub pode atrasar execuções agendadas em alturas de pico. Se um atraso grande
fizesse as duas cair na mesma hora, o `state.json` impede o envio repetido: a
segunda execução não encontra nada de novo e não envia nada.

Podes forçar uma execução a qualquer momento em `Actions` → `Digest` → `Run workflow`.
Nesse caso o filtro de hora não se aplica, e podes usar o modo seco para ver o
resultado sem receberes email.
