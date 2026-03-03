#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pr-review-insights.py

Coleta comentários de code review dos seus últimos PRs, faz review do diff
e gera insights de melhoria. Funciona sem GitHub Copilot.

Providers suportados: Claude (Anthropic), Gemini (Google), DeepSeek

Uso:
    python3 pr-review-insights.py   (Linux/Mac)
    python pr-review-insights.py    (Windows)

Requisitos:
    - gh CLI autenticado (gh auth login)
    - Chave de API do provider escolhido
"""

import subprocess
import json
import sys
import os
import re
import shutil

if sys.version_info < (3, 6):
    print("Erro: Python 3.6+ necessário. Use: python3 pr-review-insights.py")
    sys.exit(1)

_IS_WIN = sys.platform == "win32"
_SET_CMD = "set" if _IS_WIN else "export"


# ─── Instalação automática de dependências ────────────────────────────────────

def pip_install(pkg):
    cmd = [sys.executable, "-m", "pip", "install", pkg, "-q"]
    if not _IS_WIN:
        cmd.append("--break-system-packages")
    subprocess.run(cmd, check=True)


# ─── Helpers GitHub ──────────────────────────────────────────────────────────

def gh(*args, **kwargs):
    check = kwargs.get("check", True)
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        print(f"\nErro: gh {' '.join(args)}\n{result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return (result.stdout or "").strip()


def get_recent_prs(limit=80):
    raw = gh("search", "prs", "--author", "@me", "--sort", "updated",
             "--limit", str(limit), "--json", "number,repository,title,url")
    prs = json.loads(raw) if raw else []
    for pr in prs:
        nwo = pr["repository"].get("nameWithOwner", "")
        if "/" in nwo:
            owner, repo = nwo.split("/", 1)
            pr["repository"]["_owner"] = owner
            pr["repository"]["_repo"] = repo
    return prs


def get_pr_files_count(owner, repo, number):
    raw = gh("pr", "view", str(number), "--repo", f"{owner}/{repo}",
             "--json", "files", check=False)
    if not raw:
        return 0
    try:
        return len(json.loads(raw).get("files", []))
    except json.JSONDecodeError:
        return 0


def get_review_comments(owner, repo, number):
    """Coleta comentários de qualquer reviewer — humano ou bot."""
    comments = []

    raw = gh("api", f"/repos/{owner}/{repo}/pulls/{number}/comments",
             "--paginate", check=False)
    if raw:
        try:
            for c in json.loads(raw):
                body = c.get("body", "").strip()
                if body and len(body.splitlines()) > 2:
                    comments.append({
                        "file": c.get("path", ""),
                        "line": c.get("original_line") or c.get("line", ""),
                        "body": body,
                        "author": c.get("user", {}).get("login", ""),
                        "kind": "inline",
                    })
        except json.JSONDecodeError:
            pass

    raw = gh("api", f"/repos/{owner}/{repo}/pulls/{number}/reviews",
             "--paginate", check=False)
    if raw:
        try:
            for r in json.loads(raw):
                body = r.get("body", "").strip()
                if body and len(body.splitlines()) > 2:
                    comments.append({
                        "file": "sumário do review",
                        "line": "",
                        "body": body,
                        "author": r.get("user", {}).get("login", ""),
                        "kind": "review_summary",
                    })
        except json.JSONDecodeError:
            pass

    return comments


_SKIP_RE = re.compile(
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|\.lock$|"
    r"\.min\.js|\.min\.css|dist/|\.generated\.|__generated__|"
    r"\.snap$|coverage/|\.map$)",
    re.IGNORECASE,
)


def get_pr_diff(owner, repo, number, max_lines_per_file=120, max_total_chars=90_000):
    raw = gh("pr", "diff", str(number), "--repo", f"{owner}/{repo}", check=False)
    if not raw:
        return ""

    file_chunks = re.split(r"(?=^diff --git )", raw, flags=re.MULTILINE)
    result_parts = []
    total_chars = 0

    for chunk in file_chunks:
        if not chunk.strip():
            continue
        m = re.search(r"^diff --git a/(.+?) b/", chunk, re.MULTILINE)
        filename = m.group(1) if m else ""
        if filename and _SKIP_RE.search(filename):
            result_parts.append(f"diff --git a/{filename} b/{filename}\n[arquivo ignorado]\n")
            continue
        lines = chunk.splitlines()
        if len(lines) > max_lines_per_file:
            omitted = len(lines) - max_lines_per_file
            lines = lines[:max_lines_per_file] + [f"... [{omitted} linhas omitidas]"]
        part = "\n".join(lines) + "\n"
        if total_chars + len(part) > max_total_chars:
            result_parts.append("\n[diff truncado — limite de tamanho atingido]\n")
            break
        result_parts.append(part)
        total_chars += len(part)

    return "".join(result_parts)


# ─── Prompt ──────────────────────────────────────────────────────────────────

def build_prompt(all_feedback):
    prs_text = ""
    for item in all_feedback:
        prs_text += f"\n---\n## PR `{item['owner']}/{item['repo']}#{item['number']}` — {item['title']}\n"
        prs_text += f"URL: {item['url']}\n\n"

        if item["comments"]:
            prs_text += "### Comentários de review\n\n"
            for i, c in enumerate(item["comments"], 1):
                loc = f"`{c['file']}`" + (f" linha {c['line']}" if c["line"] else "")
                prs_text += f"**[{i}] @{c['author']} — {loc}**\n{c['body']}\n\n"
        else:
            prs_text += "_Sem comentários de review._\n\n"

        if item["diff"]:
            prs_text += "### Diff do PR\n\n```diff\n"
            prs_text += item["diff"]
            prs_text += "```\n\n"

    return f"""Você é um engenheiro sênior fazendo análise de code review. Analise os PRs abaixo com honestidade e objetividade. Responda em português.

{prs_text}

---

## 1. Validação dos comentários de review
Para cada comentário listado, classifique como **válido**, **dispensável** ou **debatível** — com explicação curta do porquê. Ignore comentários puramente de estilo sem impacto real.

## 2. Code review do diff
Revise o código alterado. Aponte **apenas** o que realmente importa:
- Bugs reais ou potenciais
- Problemas de segurança
- Falhas sérias de design ou arquitetura
- Problemas graves de performance

Não comente: estilo, naming subjetivo, preferências pessoais, coisas que "poderiam ser melhores mas funcionam bem". Seja cirúrgico — se não tem nada crítico, diga isso.

## 3. Padrões e insights
Com base em tudo que viu:
- Quais problemas se repetem? (agrupe por categoria)
- Quais são os débitos técnicos mais críticos?
- Onde estão as lacunas técnicas mais relevantes?
- Dicas práticas e acionáveis para os próximos PRs
- O que estudar (específico: conceito, recurso, capítulo de livro — sem genéricos)

## 4. Principais contribuições
Liste as contribuições mais relevantes encontradas nos PRs, no formato:
"[Verbo de ação] [o que foi feito] em [contexto/sistema], gerando [impacto ou resultado]"

Exemplos do formato esperado:
- "Implementei módulo de gestão de fornecedores no ERP, permitindo controle centralizado de contratos"
- "Corrigi bug crítico no fluxo de pagamento que causava duplicação de cobranças"
- "Refatorei camada de autenticação separando responsabilidades, reduzindo acoplamento entre módulos"

Regras obrigatórias:
- Só inclua se a contribuição tiver impacto real e tangível (funcionalidade nova relevante, correção crítica, melhoria arquitetural significativa)
- Se não houver contribuições que realmente valham citar, omita a seção completamente — não force
- Máximo de 5 itens; prefira menos e mais precisos
- Útil para currículo e para mostrar valor ao gestor
"""


# ─── Providers ───────────────────────────────────────────────────────────────

def _ensure_anthropic():
    try:
        import anthropic
    except ImportError:
        pip_install("anthropic")
        import anthropic
    return anthropic


def _ensure_genai():
    try:
        import google.generativeai as genai
    except ImportError:
        pip_install("google-generativeai")
        import google.generativeai as genai
    return genai


def _ensure_openai():
    try:
        from openai import OpenAI
    except ImportError:
        pip_install("openai")
        from openai import OpenAI
    return OpenAI


def test_claude(api_key):
    anthropic = _ensure_anthropic()
    anthropic.Anthropic(api_key=api_key).messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=5,
        messages=[{"role": "user", "content": "ping"}],
    )


def test_gemini(api_key):
    genai = _ensure_genai()
    genai.configure(api_key=api_key)
    genai.GenerativeModel("gemini-2.5-flash").generate_content("ping")


def test_deepseek(api_key):
    OpenAI = _ensure_openai()
    OpenAI(api_key=api_key, base_url="https://api.deepseek.com").chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=5,
    )


def run_claude(prompt, api_key):
    anthropic = _ensure_anthropic()
    client = anthropic.Anthropic(api_key=api_key)
    chunks = []
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=8096,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            chunks.append(text)
    return "".join(chunks)


def run_gemini(prompt, api_key):
    genai = _ensure_genai()
    genai.configure(api_key=api_key)

    for model_name in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"):
        try:
            model = genai.GenerativeModel(model_name)
            print(f"   Modelo: {model_name}\n")
            response = model.generate_content(prompt, stream=True)
            chunks = []
            for chunk in response:
                text = chunk.text or ""
                print(text, end="", flush=True)
                chunks.append(text)
            return "".join(chunks)
        except Exception as e:
            print(f"   {model_name} indisponível: {e}")

    print("Erro: nenhum modelo Gemini disponível.", file=sys.stderr)
    sys.exit(1)


def run_deepseek(prompt, api_key):
    OpenAI = _ensure_openai()
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    chunks = []
    stream = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        max_tokens=8000,
    )
    for chunk in stream:
        text = chunk.choices[0].delta.content or ""
        print(text, end="", flush=True)
        chunks.append(text)
    return "".join(chunks)


# ─── Seleção de provider ─────────────────────────────────────────────────────

PROVIDERS = {
    "1": {
        "name":    "Claude Opus  (Anthropic)",
        "env":     "ANTHROPIC_API_KEY",
        "fn":      run_claude,
        "test_fn": test_claude,
        "hint":    f"{_SET_CMD} ANTHROPIC_API_KEY=sk-ant-...   # console.anthropic.com",
    },
    "2": {
        "name":    "Gemini  (Google AI Studio — gratuito)",
        "env":     "GEMINI_API_KEY",
        "fn":      run_gemini,
        "test_fn": test_gemini,
        "hint":    f"{_SET_CMD} GEMINI_API_KEY=AIza...   # aistudio.google.com",
    },
    "3": {
        "name":    "DeepSeek V3  (DeepSeek — gratuito)",
        "env":     "DEEPSEEK_API_KEY",
        "fn":      run_deepseek,
        "test_fn": test_deepseek,
        "hint":    f"{_SET_CMD} DEEPSEEK_API_KEY=sk-...   # platform.deepseek.com",
    },
}


def select_provider():
    print("\nEscolha o provider de IA:\n")
    for key, p in PROVIDERS.items():
        status = "✓" if os.environ.get(p["env"]) else "✗ sem chave"
        print(f"  [{key}] {p['name']}")
        print(f"        {p['env']}  {status}")
    print()

    while True:
        choice = input("Opção [1/2/3]: ").strip()
        if choice not in PROVIDERS:
            print("  Digite 1, 2 ou 3.")
            continue

        p = PROVIDERS[choice]
        api_key = os.environ.get(p["env"])
        if not api_key:
            print(f"\n✗ {p['env']} não encontrada.")
            print(f"  {p['hint']}\n")
            sys.exit(1)

        # Testa a chave antes de começar
        print(f"   Testando conexão com {p['name']}...")
        try:
            p["test_fn"](api_key)
            print(f"   ✓ API key válida ({len(api_key)} chars)\n")
        except Exception as e:
            print(f"\n✗ Falha ao autenticar com {p['name']}")
            print(f"  Chave configurada: {len(api_key)} caracteres")
            print(f"  Erro: {e}\n")
            sys.exit(1)

        print(f"✓ Usando: {p['name']}\n")
        return p["fn"], api_key


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if shutil.which("gh") is None:
        print("Erro: gh CLI não encontrado. Instale em https://cli.github.com/", file=sys.stderr)
        sys.exit(1)

    run_fn, api_key = select_provider()

    # ── Etapa 1: PRs recentes ─────────────────────────────────────────────────
    print("🔍 Buscando seus PRs recentes...")
    recent_prs = get_recent_prs(limit=80)
    if not recent_prs:
        print("Nenhum PR encontrado.")
        sys.exit(0)
    print(f"   {len(recent_prs)} PRs encontrados. Filtrando os com >3 arquivos...\n")

    # ── Etapa 2: filtra PRs ───────────────────────────────────────────────────
    qualifying = []
    for pr in recent_prs:
        if len(qualifying) >= 10:
            break
        repo_info = pr.get("repository", {})
        owner  = repo_info.get("_owner", "")
        repo   = repo_info.get("_repo", "") or repo_info.get("name", "")
        number = pr["number"]
        if not owner or not repo:
            continue
        n_files = get_pr_files_count(owner, repo, number)
        mark = "✓" if n_files > 3 else "✗"
        print(f"   {mark}  {owner}/{repo}#{number}  ({n_files} arquivos)  {pr['title'][:55]}")
        if n_files > 3:
            qualifying.append({"owner": owner, "repo": repo, "number": number,
                                "title": pr["title"], "url": pr["url"]})

    if not qualifying:
        print("\nNenhum PR com mais de 3 arquivos encontrado nos últimos 80 PRs.")
        sys.exit(0)

    # ── Etapa 3: comentários + diff ───────────────────────────────────────────
    print(f"\n📋 Coletando reviews e diffs de {len(qualifying)} PRs...\n")
    all_feedback = []
    for pr in qualifying:
        owner, repo, number = pr["owner"], pr["repo"], pr["number"]
        print(f"   {owner}/{repo}#{number}  '{pr['title'][:50]}'")
        comments = get_review_comments(owner, repo, number)
        diff     = get_pr_diff(owner, repo, number)
        all_feedback.append({**pr, "comments": comments, "diff": diff})
        print(f"      → {len(comments)} comentário(s) | diff: {len(diff):,} chars")

    # ── Etapa 4: envia para a IA ──────────────────────────────────────────────
    prompt = build_prompt(all_feedback)
    total_comments = sum(len(f["comments"]) for f in all_feedback)

    print(f"\n{'─' * 70}")
    print(f"🤖  {len(all_feedback)} PR(s) | {total_comments} comentário(s)")
    print(f"{'─' * 70}\n")

    result = run_fn(prompt, api_key)

    print(f"\n\n{'─' * 70}\n")

    # ── Etapa 5: salva resultado ──────────────────────────────────────────────
    from datetime import datetime
    output_dir = os.path.expanduser("~/pr-insights")
    os.makedirs(output_dir, exist_ok=True)
    timestamp   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = os.path.join(output_dir, f"insights_{timestamp}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# PR Review Insights — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n")
        f.write(f"**PRs analisados:** {len(all_feedback)}\n")
        f.write(f"**Comentários coletados:** {total_comments}\n\n")
        f.write("**PRs incluídos:**\n")
        for item in all_feedback:
            f.write(f"- [{item['owner']}/{item['repo']}#{item['number']}]({item['url']}) — {item['title']}\n")
        f.write("\n---\n\n")
        f.write(result)

    print(f"💾 Salvo em: {output_path}\n")


if __name__ == "__main__":
    main()
