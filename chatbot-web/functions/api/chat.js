import { rankRecipes, readMessage, ruleReply } from "../lib/recommender.js";

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

  const state = readMessage(message, body.state);
  const results = rankRecipes(state).slice(0, 3);
  return json({ reply: ruleReply(state, results), recipes: results.map(({ card }) => card), state, mode: "rules" });
}
