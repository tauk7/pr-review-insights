# pr-review-insights

Coleta comentários de code review dos seus últimos PRs, faz review do diff e gera insights de melhoria.

Não precisa de GitHub Copilot — funciona com qualquer reviewer (humano ou bot).

## Como funciona

1. Busca seus últimos PRs em todos os repositórios (via `gh` CLI)
2. Filtra os que têm mais de 3 arquivos alterados
3. Coleta comentários de **qualquer** reviewer
4. Baixa o diff de cada PR (ignora lock files, dist, arquivos gerados)
5. Envia tudo para a IA escolhida, que:
   - Valida se os comentários existentes são válidos, dispensáveis ou debatíveis
   - Faz code review do diff — só o que realmente importa (bugs, segurança, design)
   - Gera insights: padrões recorrentes, débitos técnicos, pontos fracos, o que estudar
6. Exibe em streaming e salva em `~/pr-insights/`

## Pré-requisitos

- Node.js 22+
- [gh CLI](https://cli.github.com/) autenticado (`gh auth login`)
- Chave de API de **um** dos providers abaixo

## Providers suportados

| Provider | Modelo | Chave | Custo |
|---|---|---|---|
| **Claude** | claude-opus-4-6 | `ANTHROPIC_API_KEY` | Pago |
| **Gemini** | gemini-2.5-pro | `GEMINI_API_KEY` | Gratuito ([AI Studio](https://aistudio.google.com)) |
| **DeepSeek** | deepseek-chat (V3) | `DEEPSEEK_API_KEY` | Gratuito ([platform.deepseek.com](https://platform.deepseek.com)) |

## Uso

```bash
# Instale as dependências (primeira vez)
npm install

# Exporte a chave do provider que vai usar
export GEMINI_API_KEY='AIza...'
# ou
export DEEPSEEK_API_KEY='sk-...'
# ou
export ANTHROPIC_API_KEY='sk-ant-...'

node pr-review-insights.mjs
```

O script pergunta qual provider usar e mostra quais chaves estão configuradas.

## O que a IA analisa

- **Validação de comentários** — filtra o que vale vs. o que é ruído
- **Code review do diff** — aponta só o que compensa: bugs, segurança, design, performance
- **Padrões recorrentes** — agrupa problemas por categoria
- **Débitos técnicos críticos** — com impacto em manutenibilidade e escalabilidade
- **Pontos fracos** — diagnóstico honesto das lacunas técnicas
- **O que estudar** — recursos específicos, não genéricos
