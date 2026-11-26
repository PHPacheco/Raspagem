import assert from "node:assert/strict";
import test from "node:test";
import { onRequest } from "../functions/api/chat.js";
import { rankRecipes, readMessage } from "../functions/lib/recommender.js";

const example = "Tenho banana, aveia, cacau e ovos.";

async function post(body, AI) {
  const request = new Request("https://example.test/api/chat", {
    method: "POST", body: JSON.stringify(body)
  });
  const response = await onRequest({ request, env: { AI } });
  return { status: response.status, ...(await response.json()) };
}

test("returns the real recipe and published USDA estimate", async () => {
  const result = await post({ message: example });
  assert.equal(result.status, 200);
  assert.equal(result.mode, "rules");
  const recipe = result.recipes[0];
  assert.equal(recipe.id, "189421");
  assert.equal(recipe.score, 100);
  assert.equal(recipe.sourceUrl, "https://www.tudogostoso.com.br/receita/189421-panqueca-de-banana-fit.html");
  assert.deepEqual(recipe.nutrition.perServing, {
    caloriesKcal: 298.7, proteinG: 16.2, carbohydratesG: 37.7, fatG: 11.3
  });
});

test("keeps dietary exclusions and time limits across a continuation", async () => {
  const one = await post({ message: example + " Sem leite e até 10 minutos." });
  const two = await post({ message: "Também tenho cebola.", state: one.state });
  assert.deepEqual(two.state.available, ["banana", "aveia", "cacau", "ovo", "cebola"]);
  assert.deepEqual(two.state.excluded, ["leite"]);
  assert.ok(two.recipes.length > 0);
  assert.ok(two.recipes.every(({ prepTimeMinutes }) => prepTimeMinutes <= 10));
  assert.ok(!two.recipes.some(({ id }) => id === "173520")); // Its cheese is dairy.
});

test("matches compound foods and distinguishes absence from avoidance", () => {
  const state = readMessage("Tenho leite de coco, mas não tenho leite.");
  assert.deepEqual(state.available, ["leite de coco"]);
  assert.deepEqual(state.unavailable, ["leite"]);
  assert.deepEqual(state.excluded, []);
  const withoutDairy = readMessage("Sem leite.", state);
  const recommendations = rankRecipes(withoutDairy);
  assert.ok(recommendations.length > 0);
  assert.ok(recommendations.some(({ card }) => card.matchedIngredients.includes("leite de coco")));
  assert.ok(!recommendations.some(({ card }) => card.id === "109885")); // It also contains cream.
  assert.deepEqual(readMessage("Leite sem lactose e ovos.").available, ["leite", "ovo"]);
});

test("allows AI to choose only retrieved candidates and preserves the recipe details", async () => {
  const message = "Tenho banana, aveia e ovos. Quero algo rápido.";
  const base = await post({ message, useAi: false });
  const model = {
    async run(_name, options) {
      const data = JSON.parse(options.messages[1].content);
      if (!data.candidates) return { response: { quick: true } };
      assert.ok(data.candidates.length > 1);
      const choice = data.candidates.find((candidate) => candidate.id !== base.recipes[0].id);
      return { choices: [{ message: { content: JSON.stringify({
        recipeId: choice.id, reason: "ingredients", intro: "Eu começaria por esta opção."
      }) } }] };
    }
  };
  const result = await post({ message }, model);
  assert.equal(result.mode, "ai");
  assert.notEqual(result.recipes[0].id, base.recipes[0].id);
  assert.match(result.reply, /Eu começaria/);
  assert.deepEqual(result.recipes[0], base.recipes.find((recipe) => recipe.id === result.recipes[0].id));
});

test("uses the deterministic response if the AI fails or invents a recipe ID", async () => {
  const baseline = await post({ message: example, useAi: false });
  const unavailable = await post({ message: example }, { run: async () => { throw Error("service unavailable"); } });
  const invalid = await post({ message: example }, { run: async () => ({
    response: { recipeId: "unlisted", reason: "ingredients", intro: "Eu começaria por esta opção." }
  }) });
  assert.deepEqual(unavailable, baseline);
  assert.deepEqual(invalid, baseline);
});

test("does not recommend a zero-match recipe and limits invalid messages", async () => {
  assert.deepEqual((await post({ message: "Tenho glitter e parafuso." })).recipes, []);
  assert.equal((await post({ message: "" })).status, 400);
  assert.equal((await post({ message: "ç".repeat(4500) })).status, 413);
});
