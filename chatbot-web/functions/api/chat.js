import { rankRecipes, readMessage, ruleReply } from "../lib/recommender.js";
import { recommendWithAI } from "../lib/workers-ai.js";

const MAX_BODY_BYTES = 8192;

function json(payload, status = 200) {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" }
  });
}

async function bodyText(request) {
  if (Number(request.headers.get("content-length")) > MAX_BODY_BYTES) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let body = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return body + decoder.decode();
      bytes += value.byteLength;
      if (bytes > MAX_BODY_BYTES) {
        await reader.cancel();
        return null;
      }
      body += decoder.decode(value, { stream: true });
    }
  } finally {
    reader.releaseLock();
  }
}

export async function onRequest({ request, env }) {
  if (request.method === "OPTIONS") return new Response(null, { status: 204 });
  if (request.method !== "POST") return json({ error: "Método não permitido." }, 405);
  let body;
  try {
    const raw = await bodyText(request);
    if (raw === null) return json({ error: "Mensagem muito grande." }, 413);
    body = JSON.parse(raw);
  } catch {
    return json({ error: "JSON inválido." }, 400);
  }

  const message = typeof body?.message === "string" ? body.message.trim() : "";
  if (!message) return json({ error: "A mensagem é obrigatória." }, 400);
  if (message.length > 600) return json({ error: "Use no máximo 600 caracteres." }, 400);

  const state = readMessage(message, body.state);
  const assisted = body.useAi === false ? null : await recommendWithAI(env?.AI, message, state);
  if (assisted) {
    return json({
      reply: assisted.reply,
      recipes: assisted.results.map(({ card }) => card),
      state: assisted.state,
      mode: "ai"
    });
  }
  const results = rankRecipes(state).slice(0, 3);
  return json({ reply: ruleReply(state, results), recipes: results.map(({ card }) => card), state, mode: "rules" });
}
