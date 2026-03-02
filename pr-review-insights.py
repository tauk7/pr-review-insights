#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pr-review-insights.py

Coleta comentários do GitHub Copilot Review dos seus últimos PRs
(com >3 arquivos alterados) e envia para o Claude analisar seus
padrões de código, débitos técnicos e o que estudar.

Uso:
    python3 pr-review-insights.py

Requisitos:
    - gh CLI autenticado (gh auth login)
    - ANTHROPIC_API_KEY exportada no ambiente
"""

import subprocess
import json
import sys
import os


# ─── Instalação automática do SDK ────────────────────────────────────────────

try:
    import anthropic
except ImportError:
    print("Pacote 'anthropic' não encontrado. Instalando...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "anthropic", "-q", "--break-system-packages"],
        check=True,
    )
    import anthropic


# ─── Helpers GitHub ──────────────────────────────────────────────────────────

def gh(*args, check=True):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"\nErro ao executar: gh {' '.join(args)}\n{result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_recent_prs(limit=80):
    """Busca PRs recentes do usuário autenticado em todos os repos."""
    raw = gh(
        "search", "prs",
        "--author", "@me",
        "--sort", "updated",
        "--limit", str(limit),
        "--json", "number,repository,title,url",
    )
    prs = json.loads(raw) if raw else []
    # Normaliza: extrai owner e repo de nameWithOwner (ex: "FieldControl/mordor-2")
    for pr in prs:
        name_with_owner = pr["repository"].get("nameWithOwner", "")
        if "/" in name_with_owner:
            owner, repo = name_with_owner.split("/", 1)
            pr["repository"]["_owner"] = owner
            pr["repository"]["_repo"] = repo
    return prs


def get_pr_files_count(owner, repo, number):
    """Retorna a quantidade de arquivos alterados no PR."""
    raw = gh("pr", "view", str(number), "--repo", f"{owner}/{repo}", "--json", "files", check=False)
    if not raw:
        return 0
    try:
        return len(json.loads(raw).get("files", []))
    except json.JSONDecodeError:
        return 0


def get_copilot_comments(owner, repo, number):
    """
    Coleta todos os comentários do Copilot bot no PR:
    - Comentários inline (review comments em linhas de código)
    - Corpo do review (sumário geral do Copilot)
    """
    comments = []

    # Comentários inline nas linhas de código
    raw = gh("api", f"/repos/{owner}/{repo}/pulls/{number}/comments",
             "--paginate", check=False)
    if raw:
        try:
            for c in json.loads(raw):
                login = c.get("user", {}).get("login", "").lower()
                if "copilot" in login:
                    body = c.get("body", "").strip()
                    if body:
                        comments.append({
                            "file": c.get("path", ""),
                            "line": c.get("original_line") or c.get("line", ""),
                            "body": body,
                            "kind": "inline",
                        })
        except json.JSONDecodeError:
            pass

    # Corpo completo do review (sumário)
    raw = gh("api", f"/repos/{owner}/{repo}/pulls/{number}/reviews",
             "--paginate", check=False)
    if raw:
        try:
            for r in json.loads(raw):
                login = r.get("user", {}).get("login", "").lower()
                if "copilot" in login:
                    body = r.get("body", "").strip()
                    if body:
                        comments.append({
                            "file": "sumário do review",
                            "line": "",
                            "body": body,
                            "kind": "review_summary",
                        })
        except json.JSONDecodeError:
            pass

    return comments


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Pré-checks
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Erro: variável de ambiente ANTHROPIC_API_KEY não está definida.", file=sys.stderr)
        print("Execute: export ANTHROPIC_API_KEY='sua-chave'", file=sys.stderr)
        sys.exit(1)

    if subprocess.run(["which", "gh"], capture_output=True).returncode != 0:
        print("Erro: gh CLI não encontrado. Instale em https://cli.github.com/", file=sys.stderr)
        sys.exit(1)

    # ── Etapa 1: buscar PRs recentes ─────────────────────────────────────────
    print("\n🔍 Buscando seus PRs recentes...")
    recent_prs = get_recent_prs(limit=80)
    if not recent_prs:
        print("Nenhum PR encontrado.")
        sys.exit(0)
    print(f"   {len(recent_prs)} PRs encontrados. Filtrando os com >3 arquivos alterados...\n")

    # ── Etapa 2: filtrar PRs com mais de 3 arquivos ──────────────────────────
    qualifying = []
    for pr in recent_prs:
        if len(qualifying) >= 10:
            break

        repo_info = pr.get("repository", {})
        owner = repo_info.get("_owner", "")
        repo  = repo_info.get("_repo", "") or repo_info.get("name", "")
        number = pr["number"]

        if not owner or not repo:
            continue

        n_files = get_pr_files_count(owner, repo, number)
        mark = "✓" if n_files > 3 else "✗"
        print(f"   {mark}  {owner}/{repo}#{number}  ({n_files} arquivos)  {pr['title'][:55]}")

        if n_files > 3:
            qualifying.append({
                "owner":  owner,
                "repo":   repo,
                "number": number,
                "title":  pr["title"],
                "url":    pr["url"],
            })

    if not qualifying:
        print("\nNenhum PR com mais de 3 arquivos alterados encontrado nos últimos 80 PRs.")
        sys.exit(0)

    # ── Etapa 3: coletar comentários do Copilot ──────────────────────────────
    print(f"\n📋 Coletando reviews do Copilot de {len(qualifying)} PRs...\n")

    all_feedback = []
    for pr in qualifying:
        owner, repo, number = pr["owner"], pr["repo"], pr["number"]
        print(f"   Lendo {owner}/{repo}#{number}...")

        comments = get_copilot_comments(owner, repo, number)

        # Manter apenas comentários com mais de 5 linhas
        significant = [
            c for c in comments
            if len(c["body"].splitlines()) > 5
        ]

        if significant:
            all_feedback.append({**pr, "comments": significant})
            print(f"      → {len(significant)} comentário(s) significativo(s) encontrado(s)")
        else:
            skipped = len(comments)
            if skipped:
                print(f"      → {skipped} comentário(s) encontrado(s), mas nenhum com >10 linhas")
            else:
                print("      → Sem comentários do Copilot")

    if not all_feedback:
        print("\nNenhum comentário do Copilot com mais de 10 linhas encontrado.")
        print("Dica: verifique se o Copilot Code Review está ativo nos seus repositórios.")
        sys.exit(0)

    total_comments = sum(len(f["comments"]) for f in all_feedback)
    print(f"\n✅ {total_comments} comentário(s) coletado(s) de {len(all_feedback)} PR(s).")

    # ── Etapa 4: montar prompt ───────────────────────────────────────────────
    feedback_text = ""
    for item in all_feedback:
        feedback_text += f"\n---\n## PR: `{item['owner']}/{item['repo']}#{item['number']}`\n"
        feedback_text += f"**Título:** {item['title']}\n"
        feedback_text += f"**URL:** {item['url']}\n\n"
        for i, c in enumerate(item["comments"], 1):
            loc = f"`{c['file']}`" + (f" linha {c['line']}" if c["line"] else "")
            feedback_text += f"### Comentário {i} — {loc}\n"
            feedback_text += c["body"] + "\n\n"

    prompt = f"""Analise os seguintes comentários de code review feitos pelo **GitHub Copilot** \
nos meus Pull Requests recentes. Esses comentários foram filtrados para incluir apenas os \
mais detalhados (>10 linhas), portanto são os feedbacks mais ricos e relevantes.

{feedback_text}

---

Com base nesses comentários, faça uma análise profunda e honesta. Responda em português e \
seja direto — sem eufemismos, fale claramente sobre os problemas encontrados.

## 1. Padrões de Problemas Recorrentes
Identifique os tipos de problemas que se repetem. Agrupe por categoria \
(ex: segurança, performance, legibilidade, arquitetura, tratamento de erros, testes).

## 2. Principais Débitos Técnicos
Liste os débitos técnicos mais críticos presentes no código, com impacto estimado \
em manutenibilidade, segurança ou escalabilidade.

## 3. Meus Pontos Fracos como Programador
Com base nos padrões identificados, seja honesto sobre onde estão minhas lacunas técnicas.

## 4. Dicas Práticas e Acionáveis
Para cada ponto fraco, dê uma dica concreta do que posso fazer diferente \
a partir de agora — algo que eu possa aplicar no próximo PR.

## 5. O que Estudar
Liste tópicos específicos, conceitos, padrões de design, livros, artigos ou \
recursos para pesquisar. Seja específico (ex: "Clean Code cap. 3 — Funções", \
"OWASP Top 10 — Injection", "Padrão Repository em DDD") em vez de genérico.
"""

    # ── Etapa 5: enviar para Claude com streaming ────────────────────────────
    from datetime import datetime

    print(f"\n{'─' * 70}")
    print("🤖 Análise do Claude Opus 4.6")
    print(f"{'─' * 70}\n")

    client = anthropic.Anthropic()
    result_chunks = []

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=8096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            result_chunks.append(text)

    print(f"\n\n{'─' * 70}\n")

    # ── Etapa 6: salvar resultado ─────────────────────────────────────────────
    output_dir = os.path.expanduser("~/pr-insights")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = os.path.join(output_dir, f"insights_{timestamp}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# PR Review Insights — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n")
        f.write(f"**PRs analisados:** {len(all_feedback)}\n")
        f.write(f"**Comentários coletados:** {total_comments}\n\n")
        f.write("**PRs incluídos:**\n")
        for item in all_feedback:
            f.write(f"- [{item['owner']}/{item['repo']}#{item['number']}]({item['url']}) — {item['title']}\n")
        f.write("\n---\n\n")
        f.write("".join(result_chunks))

    print(f"💾 Resultado salvo em: {output_path}\n")


if __name__ == "__main__":
    main()
