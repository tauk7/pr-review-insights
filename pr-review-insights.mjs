#!/usr/bin/env node
// -*- coding: utf-8 -*-
/**
 * pr-review-insights.mjs
 *
 * Coleta comentários de code review dos seus últimos PRs, faz review do diff
 * e gera insights de melhoria. Funciona sem GitHub Copilot.
 *
 * Providers suportados: Claude (Anthropic), Gemini (Google), DeepSeek
 *
 * Uso:
 *     node pr-review-insights.mjs
 *
 * Requisitos:
 *     - gh CLI autenticado (gh auth login)
 *     - Chave de API do provider escolhido
 */

import { execFileSync } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
const _IS_WIN = process.platform === "win32";
const _SET_CMD = _IS_WIN ? "set" : "export";

// ─── Helpers GitHub ──────────────────────────────────────────────────────────

function gh(...args) {
  const check = typeof args[args.length - 1] === "object" ? args.pop() : {};
  const shouldCheck = check.check !== false;

  try {
    const stdout = execFileSync("gh", args, {
      encoding: "utf-8",
      maxBuffer: 50 * 1024 * 1024,
    });
    return (stdout || "").trim();
  } catch (err) {
    if (shouldCheck) {
      console.error(`\nErro: gh ${args.join(" ")}\n${err.stderr || err.message}`);
      process.exit(1);
    }
    return "";
  }
}

function getRecentPrs(limit = 80) {
  const raw = gh(
    "search", "prs", "--author", "@me", "--sort", "updated",
    "--limit", String(limit), "--json", "number,repository,title,url"
  );
  const prs = raw ? JSON.parse(raw) : [];
  for (const pr of prs) {
    const nwo = pr.repository?.nameWithOwner || "";
    if (nwo.includes("/")) {
      const [owner, repo] = nwo.split("/", 2);
      pr.repository._owner = owner;
      pr.repository._repo = repo;
    }
  }
  return prs;
}

function getPrFilesCount(owner, repo, number) {
  const raw = gh(
    "pr", "view", String(number), "--repo", `${owner}/${repo}`,
    "--json", "files", { check: false }
  );
  if (!raw) return 0;
  try {
    return (JSON.parse(raw).files || []).length;
  } catch {
    return 0;
  }
}

function getReviewComments(owner, repo, number) {
  const comments = [];

  const rawComments = gh(
    "api", `/repos/${owner}/${repo}/pulls/${number}/comments`,
    "--paginate", { check: false }
  );
  if (rawComments) {
    try {
      for (const c of JSON.parse(rawComments)) {
        const body = (c.body || "").trim();
        if (body && body.split("\n").length > 2) {
          comments.push({
            file: c.path || "",
            line: c.original_line || c.line || "",
            body,
            author: c.user?.login || "",
            kind: "inline",
          });
        }
      }
    } catch { /* ignore parse errors */ }
  }

  const rawReviews = gh(
    "api", `/repos/${owner}/${repo}/pulls/${number}/reviews`,
    "--paginate", { check: false }
  );
  if (rawReviews) {
    try {
      for (const r of JSON.parse(rawReviews)) {
        const body = (r.body || "").trim();
        if (body && body.split("\n").length > 2) {
          comments.push({
            file: "sumário do review",
            line: "",
            body,
            author: r.user?.login || "",
            kind: "review_summary",
          });
        }
      }
    } catch { /* ignore parse errors */ }
  }

  return comments;
}

const _SKIP_RE = new RegExp(
  "(package-lock\\.json|yarn\\.lock|pnpm-lock\\.yaml|\\.lock$|" +
  "\\.min\\.js|\\.min\\.css|dist/|\\.generated\\.|__generated__|" +
  "\\.snap$|coverage/|\\.map$)",
  "i"
);

function getPrDiff(owner, repo, number, maxLinesPerFile = 120, maxTotalChars = 90_000) {
  const raw = gh("pr", "diff", String(number), "--repo", `${owner}/${repo}`, { check: false });
  if (!raw) return "";

  const fileChunks = raw.split(/(?=^diff --git )/m);
  const resultParts = [];
  let totalChars = 0;

  for (const chunk of fileChunks) {
    if (!chunk.trim()) continue;
    const m = chunk.match(/^diff --git a\/(.+?) b\//m);
    const filename = m ? m[1] : "";
    if (filename && _SKIP_RE.test(filename)) {
      resultParts.push(`diff --git a/${filename} b/${filename}\n[arquivo ignorado]\n`);
      continue;
    }
    let lines = chunk.split("\n");
    if (lines.length > maxLinesPerFile) {
      const omitted = lines.length - maxLinesPerFile;
      lines = [...lines.slice(0, maxLinesPerFile), `... [${omitted} linhas omitidas]`];
    }
    const part = lines.join("\n") + "\n";
    if (totalChars + part.length > maxTotalChars) {
      resultParts.push("\n[diff truncado — limite de tamanho atingido]\n");
      break;
    }
    resultParts.push(part);
    totalChars += part.length;
  }

  return resultParts.join("");
}

// ─── Prompt ──────────────────────────────────────────────────────────────────

function buildPrompt(allFeedback, mode = "both") {
  const useComments = mode === "comments" || mode === "both";
  const useDiff = mode === "diff" || mode === "both";

  let prsText = "";
  for (const item of allFeedback) {
    prsText += `\n---\n## PR \`${item.owner}/${item.repo}#${item.number}\` — ${item.title}\n`;
    prsText += `URL: ${item.url}\n\n`;

    if (useComments) {
      if (item.comments.length > 0) {
        prsText += "### Comentários de review\n\n";
        item.comments.forEach((c, i) => {
          const loc = `\`${c.file}\`` + (c.line ? ` linha ${c.line}` : "");
          prsText += `**[${i + 1}] @${c.author} — ${loc}**\n${c.body}\n\n`;
        });
      } else {
        prsText += "_Sem comentários de review._\n\n";
      }
    }

    if (useDiff && item.diff) {
      prsText += "### Diff do PR\n\n```diff\n";
      prsText += item.diff;
      prsText += "```\n\n";
    }
  }

  let sections = "";

  if (useComments) {
    sections += `## 1. Validação dos comentários de review
Para cada comentário listado, classifique como **válido**, **dispensável** ou **debatível** — com explicação curta do porquê. Ignore comentários puramente de estilo sem impacto real.

`;
  }

  if (useDiff) {
    sections += `## 2. Code review do diff
Revise o código alterado. Aponte **apenas** o que realmente importa:
- Bugs reais ou potenciais
- Problemas de segurança
- Falhas sérias de design ou arquitetura
- Problemas graves de performance

Não comente: estilo, naming subjetivo, preferências pessoais, coisas que "poderiam ser melhores mas funcionam bem". Seja cirúrgico — se não tem nada crítico, diga isso.

`;
  }

  sections += `## 3. Padrões e insights
Com base em tudo que viu:
- Quais problemas se repetem? (agrupe por categoria)
- Quais são os débitos técnicos mais críticos?
- Onde estão as lacunas técnicas mais relevantes?
- Dicas práticas e acionáveis para os próximos PRs
- O que estudar (específico: conceito, recurso, capítulo de livro — sem genéricos)

## 4. Principais contribuições (formato XYZ para currículo/gestor)
Use a fórmula XYZ do Google: "[Verbo] [X — resultado de negócio], [Y — métrica ou magnitude], ao [Z — ação técnica em linguagem universal]."

Onde:
- X = impacto de negócio (segurança, confiabilidade, velocidade, UX, custo) — nunca tecnologia
- Y = métrica ou estimativa honesta ("eliminando completamente", "reduzindo significativamente") — nunca invente números
- Z = ação técnica resumida de forma que qualquer dev entenda sem conhecer o projeto

Exemplos do formato esperado:
- "Mitigei falhas críticas de acesso indevido a dados de outros usuários, reduzindo a zero os incidentes de vazamento entre contas, ao implementar validação rigorosa de propriedade nas mutations da API GraphQL."
- "Aumentei a confiabilidade da camada de dados, eliminando bugs silenciosos que corrompiam resultados de consultas, ao reescrever a abstração de repositório que ignorava filtros aplicados."
- "Melhorei a capacidade de resposta a incidentes em produção, reduzindo o tempo de diagnóstico de falhas, ao injetar logs estruturados com contexto de usuário em todas as requisições HTTP da API."

Regras obrigatórias:
- Só inclua contribuições com impacto real: feature crítica, bug grave corrigido, ganho de segurança, performance relevante
- Não mencione nomes internos de sistemas, codinomes de projetos ou tecnologias que não agregam à frase
- Se a contribuição for pequena demais ou só fizer sentido dentro do contexto do projeto, descarte — não force
- Máximo de 5 itens; 2 contribuições fortes valem mais que 5 genéricas`;

  return `Você é um engenheiro sênior fazendo análise de code review. Analise os PRs abaixo com honestidade e objetividade. Responda em português.

${prsText}

---

${sections}`;
}

// ─── Providers ───────────────────────────────────────────────────────────────

async function testClaude(apiKey) {
  const { default: Anthropic } = await import("@anthropic-ai/sdk");
  const client = new Anthropic({ apiKey });
  await client.messages.create({
    model: "claude-haiku-4-5-20251001",
    max_tokens: 5,
    messages: [{ role: "user", content: "ping" }],
  });
}

async function testGemini(apiKey) {
  const { GoogleGenerativeAI } = await import("@google/generative-ai");
  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({ model: "gemini-2.5-flash" });
  await model.generateContent("ping");
}

async function testDeepseek(apiKey) {
  const { default: OpenAI } = await import("openai");
  const client = new OpenAI({ apiKey, baseURL: "https://api.deepseek.com" });
  await client.chat.completions.create({
    model: "deepseek-chat",
    messages: [{ role: "user", content: "ping" }],
    max_tokens: 5,
  });
}

async function runClaude(prompt, apiKey) {
  const { default: Anthropic } = await import("@anthropic-ai/sdk");
  const client = new Anthropic({ apiKey });
  const chunks = [];
  const stream = client.messages.stream({
    model: "claude-opus-4-6",
    max_tokens: 8096,
    messages: [{ role: "user", content: prompt }],
  });
  for await (const event of stream) {
    if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
      process.stdout.write(event.delta.text);
      chunks.push(event.delta.text);
    }
  }
  return chunks.join("");
}

async function runGemini(prompt, apiKey) {
  const { GoogleGenerativeAI } = await import("@google/generative-ai");
  const genAI = new GoogleGenerativeAI(apiKey);

  for (const modelName of ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"]) {
    try {
      const model = genAI.getGenerativeModel({ model: modelName });
      console.log(`   Modelo: ${modelName}\n`);
      const result = await model.generateContentStream(prompt);
      const chunks = [];
      for await (const chunk of result.stream) {
        const text = chunk.text() || "";
        process.stdout.write(text);
        chunks.push(text);
      }
      return chunks.join("");
    } catch (e) {
      console.log(`   ${modelName} indisponível: ${e.message}`);
    }
  }

  console.error("Erro: nenhum modelo Gemini disponível.");
  process.exit(1);
}

async function runDeepseek(prompt, apiKey) {
  const { default: OpenAI } = await import("openai");
  const client = new OpenAI({ apiKey, baseURL: "https://api.deepseek.com" });
  const chunks = [];
  const stream = await client.chat.completions.create({
    model: "deepseek-chat",
    messages: [{ role: "user", content: prompt }],
    stream: true,
    max_tokens: 8000,
  });
  for await (const chunk of stream) {
    const text = chunk.choices[0]?.delta?.content || "";
    process.stdout.write(text);
    chunks.push(text);
  }
  return chunks.join("");
}

// ─── Seleção de provider ─────────────────────────────────────────────────────

const PROVIDERS = {
  "1": {
    name: "Claude Opus  (Anthropic)",
    env: "ANTHROPIC_API_KEY",
    fn: runClaude,
    testFn: testClaude,
    hint: `${_SET_CMD} ANTHROPIC_API_KEY=sk-ant-...   # console.anthropic.com`,
  },
  "2": {
    name: "Gemini  (Google AI Studio — gratuito)",
    env: "GEMINI_API_KEY",
    fn: runGemini,
    testFn: testGemini,
    hint: `${_SET_CMD} GEMINI_API_KEY=AIza...   # aistudio.google.com`,
  },
  "3": {
    name: "DeepSeek V3  (DeepSeek — gratuito)",
    env: "DEEPSEEK_API_KEY",
    fn: runDeepseek,
    testFn: testDeepseek,
    hint: `${_SET_CMD} DEEPSEEK_API_KEY=sk-...   # platform.deepseek.com`,
  },
};

function ask(rl, question) {
  return new Promise((resolve) => rl.question(question, resolve));
}

async function selectProvider(rl) {
  console.log("\nEscolha o provider de IA:\n");
  for (const [key, p] of Object.entries(PROVIDERS)) {
    const status = process.env[p.env] ? "✓" : "✗ sem chave";
    console.log(`  [${key}] ${p.name}`);
    console.log(`        ${p.env}  ${status}`);
  }
  console.log();

  while (true) {
    const choice = (await ask(rl, "Opção [1/2/3]: ")).trim();
    if (!PROVIDERS[choice]) {
      console.log("  Digite 1, 2 ou 3.");
      continue;
    }

    const p = PROVIDERS[choice];
    const apiKey = process.env[p.env];
    if (!apiKey) {
      console.log(`\n✗ ${p.env} não encontrada.`);
      console.log(`  ${p.hint}\n`);
      process.exit(1);
    }

    console.log(`   Testando conexão com ${p.name}...`);
    try {
      await p.testFn(apiKey);
      console.log(`   ✓ API key válida (${apiKey.length} chars)\n`);
    } catch (e) {
      console.log(`\n✗ Falha ao autenticar com ${p.name}`);
      console.log(`  Chave configurada: ${apiKey.length} caracteres`);
      console.log(`  Erro: ${e.message}\n`);
      process.exit(1);
    }

    console.log(`✓ Usando: ${p.name}\n`);
    return { fn: p.fn, apiKey };
  }
}

async function selectMode(rl) {
  const MODES = {
    "1": ["comments", "Comentários de reviewers  — valida o que foi apontado nas revisões"],
    "2": ["diff", "Review do diff pela IA    — analisa o código diretamente"],
    "3": ["both", "Ambos                     — comentários + review do diff"],
  };

  console.log("O que usar como base para análise?\n");
  for (const [key, [, desc]] of Object.entries(MODES)) {
    console.log(`  [${key}] ${desc}`);
  }
  console.log();

  while (true) {
    const choice = (await ask(rl, "Opção [1/2/3]: ")).trim();
    if (MODES[choice]) {
      const [mode, desc] = MODES[choice];
      console.log(`✓ Modo: ${desc.trim()}\n`);
      return mode;
    }
    console.log("  Digite 1, 2 ou 3.");
  }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  try {
    execFileSync("gh", ["--version"], { encoding: "utf-8" });
  } catch {
    console.error("Erro: gh CLI não encontrado. Instale em https://cli.github.com/");
    process.exit(1);
  }

  const rl = createInterface({ input: process.stdin, output: process.stdout });

  try {
    const { fn: runFn, apiKey } = await selectProvider(rl);
    const mode = await selectMode(rl);
    rl.close();

    // ── Etapa 1: PRs recentes ─────────────────────────────────────────────
    console.log("🔍 Buscando seus PRs recentes...");
    const recentPrs = getRecentPrs(80);
    if (recentPrs.length === 0) {
      console.log("Nenhum PR encontrado.");
      process.exit(0);
    }
    console.log(`   ${recentPrs.length} PRs encontrados. Filtrando os com >3 arquivos...\n`);

    // ── Etapa 2: filtra PRs ───────────────────────────────────────────────
    const qualifying = [];
    for (const pr of recentPrs) {
      if (qualifying.length >= 10) break;
      const repoInfo = pr.repository || {};
      const owner = repoInfo._owner || "";
      const repo = repoInfo._repo || repoInfo.name || "";
      const number = pr.number;
      if (!owner || !repo) continue;
      const nFiles = getPrFilesCount(owner, repo, number);
      const mark = nFiles > 3 ? "✓" : "✗";
      console.log(`   ${mark}  ${owner}/${repo}#${number}  (${nFiles} arquivos)  ${pr.title.slice(0, 55)}`);
      if (nFiles > 3) {
        qualifying.push({ owner, repo, number, title: pr.title, url: pr.url });
      }
    }

    if (qualifying.length === 0) {
      console.log("\nNenhum PR com mais de 3 arquivos encontrado nos últimos 80 PRs.");
      process.exit(0);
    }

    // ── Etapa 3: comentários + diff ───────────────────────────────────────
    console.log(`\n📋 Coletando reviews e diffs de ${qualifying.length} PRs...\n`);
    const allFeedback = [];
    for (const pr of qualifying) {
      const { owner, repo, number } = pr;
      console.log(`   ${owner}/${repo}#${number}  '${pr.title.slice(0, 50)}'`);
      const comments = (mode === "comments" || mode === "both")
        ? getReviewComments(owner, repo, number)
        : [];
      const diff = (mode === "diff" || mode === "both")
        ? getPrDiff(owner, repo, number)
        : "";
      allFeedback.push({ ...pr, comments, diff });
      const parts = [];
      if (comments.length > 0) parts.push(`${comments.length} comentário(s)`);
      if (diff) parts.push(`diff: ${diff.length.toLocaleString()} chars`);
      console.log(`      → ${parts.join(", ") || "sem dados"}`);
    }

    // ── Etapa 4: envia para a IA ──────────────────────────────────────────
    const prompt = buildPrompt(allFeedback, mode);
    const totalComments = allFeedback.reduce((sum, f) => sum + f.comments.length, 0);

    console.log(`\n${"─".repeat(70)}`);
    console.log(`🤖  ${allFeedback.length} PR(s) | ${totalComments} comentário(s)`);
    console.log(`${"─".repeat(70)}\n`);

    const result = await runFn(prompt, apiKey);

    console.log(`\n\n${"─".repeat(70)}\n`);

    // ── Etapa 5: salva resultado ──────────────────────────────────────────
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const timestamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
    const dateStr = `${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()} ${pad(now.getHours())}:${pad(now.getMinutes())}`;

    const outputDir = join(homedir(), "pr-insights");
    mkdirSync(outputDir, { recursive: true });
    const outputPath = join(outputDir, `insights_${timestamp}.md`);

    let content = `# PR Review Insights — ${dateStr}\n\n`;
    content += `**PRs analisados:** ${allFeedback.length}\n`;
    content += `**Comentários coletados:** ${totalComments}\n\n`;
    content += "**PRs incluídos:**\n";
    for (const item of allFeedback) {
      content += `- [${item.owner}/${item.repo}#${item.number}](${item.url}) — ${item.title}\n`;
    }
    content += "\n---\n\n";
    content += result;

    writeFileSync(outputPath, content, "utf-8");
    console.log(`💾 Salvo em: ${outputPath}\n`);
  } catch (err) {
    rl.close();
    throw err;
  }
}

main();
