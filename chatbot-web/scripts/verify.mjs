import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";

const args = process.argv.slice(2);
const url = new URL(args.find((arg) => !arg.startsWith("--")) ?? "http://127.0.0.1:8788");
const requireAi = args.includes("--require-ai");
const endpoint = new URL("/api/chat", url);

async function send(message, useAi, state) {
  const start = performance.now();
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, useAi, state }),
    signal: AbortSignal.timeout(25000)
  });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.ok(typeof result.reply === "string" && result.reply.length > 0);
  assert.ok(Array.isArray(result.recipes) && result.recipes.length <= 3);
  assert.ok(result.recipes.every((card) =>
    card.sourceUrl.startsWith("https://") && !card.sourceUrl.endsWith("-html-salvo.html")));
  return { ...result, ms: Math.round(performance.now() - start) };
}

const page = await fetch(url, { signal: AbortSignal.timeout(10000) });
assert.equal(page.status, 200);
assert.match(await page.text(), /Panela Aberta/);
const rows = [];
const expectations = [];
for (const useAi of [false, true]) {
  const banana = await send("Tenho banana, aveia, cacau e ovos.", useAi);
  assert.equal(banana.recipes[0]?.id, "189421");
  assert.equal(banana.recipes[0]?.nutrition?.perServing.caloriesKcal, 298.7);

  const followUp = await send("Também tenho cebola. Sem leite e com até 10 minutos.", useAi, banana.state);
  assert.ok(followUp.state.available.includes("banana") && followUp.state.available.includes("cebola"));
  assert.ok(followUp.state.excluded.includes("leite"));
  assert.ok(followUp.recipes.length && followUp.recipes.every((card) => card.prepTimeMinutes <= 10));
  assert.ok(!followUp.recipes.some(({ id }) => id === "173520"));

  const coconut = await send("Tenho leite de coco, mas não tenho leite.", useAi);
  assert.ok(coconut.state.available.includes("leite de coco") && !coconut.state.available.includes("leite"));
  const noMatch = await send("Tenho glitter e parafuso.", useAi);
  assert.equal(noMatch.recipes.length, 0);

  for (const [scenario, result] of Object.entries({ panqueca: banana, continuação: followUp, coco: coconut, "sem correspondência": noMatch })) {
    rows.push({
      cenário: scenario,
      solicitação: useAi ? "automática" : "regras",
      modo: result.mode,
      primeira: result.recipes[0]?.title ?? "—",
      faltantes: result.recipes[0]?.missingIngredients.length ?? "—",
      ms: result.ms
    });
  }
  if (useAi && requireAi) expectations.push(banana.mode, followUp.mode, coconut.mode);
}

console.table(rows);
if (requireAi) assert.ok(expectations.every((mode) => mode === "ai"), "Confira o binding AI e a resposta do modelo no Cloudflare.");
console.log("Catálogo, fonte, macros, filtros e continuidade verificados.");
