import catalog from "../data/recipes.json" with { type: "json" };

function normalize(text) {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().match(/[a-z0-9]+/g)?.join(" ") ?? "";
}

function rankRecipes(message) {
  const query = " " + normalize(message) + " ";
  return catalog.map((recipe) => {
    const matched = recipe.ingredients.filter(({ name }) => query.includes(" " + name + " "));
    return {
      id: recipe.id,
      title: recipe.title,
      sourceUrl: recipe.sourceUrl,
      prepTimeMinutes: recipe.prepTimeMinutes,
      servings: recipe.servings,
      matchedIngredients: matched.map(({ label }) => label),
      missingIngredients: recipe.ingredients.filter((item) => !matched.includes(item)).map(({ label }) => label),
      score: Math.round(100 * matched.length / recipe.ingredients.length)
    };
  })
    .filter(({ matchedIngredients }) => matchedIngredients.length > 0)
    .sort((a, b) => b.score - a.score || a.missingIngredients.length - b.missingIngredients.length)
    .slice(0, 3);
}

function json(payload, status = 200) {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" }
  });
}

export async function onRequest({ request }) {
  if (request.method === "OPTIONS") return new Response(null, { status: 204 });
  if (request.method !== "POST") return json({ error: "Método não permitido." }, 405);
  if (Number(request.headers.get("content-length")) > 8192) {
    return json({ error: "Mensagem muito grande." }, 413);
  }

  let body;
  try {
    const raw = await request.text();
    if (new TextEncoder().encode(raw).length > 8192) {
      return json({ error: "Mensagem muito grande." }, 413);
    }
    body = JSON.parse(raw);
  } catch {
    return json({ error: "JSON inválido." }, 400);
  }

  const message = typeof body?.message === "string" ? body.message.trim() : "";
  if (!message) return json({ error: "A mensagem é obrigatória." }, 400);
  if (message.length > 600) return json({ error: "Use no máximo 600 caracteres." }, 400);

  const recipes = rankRecipes(message);
  return json({
    reply: recipes.length
      ? "Encontrei opções no catálogo e ordenei pelo aproveitamento dos ingredientes."
      : "Ainda não encontrei uma receita com esses ingredientes. O que mais você tem em casa?",
    recipes,
    mode: "rules"
  });
}
