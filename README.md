# pr-review-insights

Coleta os comentários do **GitHub Copilot Review** dos seus últimos PRs e envia para o **Claude Opus 4.6** analisar seus padrões de código — apontando débitos técnicos, pontos fracos e o que estudar.

## Como funciona

1. Busca seus últimos PRs em todos os repositórios (via `gh` CLI)
2. Filtra os que têm mais de 3 arquivos alterados
3. Coleta os comentários do `github-copilot[bot]` com mais de 5 linhas
4. Envia tudo pro Claude Opus 4.6 e exibe a análise em streaming
5. Salva o resultado em `~/pr-insights/insights_YYYY-MM-DD_HH-MM-SS.md`

## Pré-requisitos

- Python 3.6+
- [gh CLI](https://cli.github.com/) autenticado (`gh auth login`)
- Chave da [Anthropic API](https://console.anthropic.com/)

## Instalação

```bash
git clone https://github.com/tauk7/pr-review-insights
cd pr-review-insights
```

O pacote `anthropic` é instalado automaticamente na primeira execução.

## Uso

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
python3 pr-review-insights.py
```

Os resultados ficam salvos em `~/pr-insights/`.

## O que o Claude analisa

- **Padrões de problemas recorrentes** — agrupados por categoria (segurança, performance, arquitetura...)
- **Principais débitos técnicos** — com impacto estimado em manutenibilidade e escalabilidade
- **Pontos fracos** — diagnóstico honesto sobre lacunas técnicas
- **Dicas práticas** — ações concretas para aplicar no próximo PR
- **O que estudar** — recursos específicos, não genéricos
