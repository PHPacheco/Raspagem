const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const submitButton = form.querySelector("button[type='submit']");
const clearButton = document.querySelector("#clear-chat");
const recipeTemplate = document.querySelector("#recipe-template");
const initialMessage = messages.firstElementChild.cloneNode(true);
const promptButtons = [...document.querySelectorAll("[data-prompt]")];
const nutritionNumber = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

let conversationState = null;
let pending = null;
let retryButton = null;

function createMessage(text, fromUser = false) {
  const article = document.createElement("article");
  article.className = fromUser ? "message message-user" : "message message-bot";
  article.setAttribute("aria-label", fromUser ? "Você" : "Panela Aberta");

  if (!fromUser) {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "PA";
    article.append(avatar);
  }

  const body = document.createElement("div");
  body.className = "message-body";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.append(paragraph);
  article.append(body);
  return { article, body };
}

function bringIntoView(article, showTranscript = false) {
  messages.scrollTop = article.offsetTop - messages.firstElementChild.offsetTop;
  if (!showTranscript) return;

  const { top, height } = article.getBoundingClientRect();
  if (top < 0 || top + Math.min(height, 96) > window.innerHeight) {
    messages.scrollIntoView({ block: "start" });
  }
}

function renderNutrition(container, nutrition) {
  if (!nutrition?.perServing) {
    const unavailable = document.createElement("p");
    unavailable.className = "nutrition-unavailable";
    unavailable.textContent = "Estimativa nutricional indisponível.";
    container.append(unavailable);
    return;
  }

  const title = document.createElement("p");
  title.className = "nutrition-title";
  title.textContent = "Estimativa por porção";
  const values = document.createElement("dl");
  values.className = "nutrition-values";

  for (const [key, label, unit] of [
    ["caloriesKcal", "Calorias", "kcal"],
    ["proteinG", "Proteínas", "g"],
    ["carbohydratesG", "Carboidratos", "g"],
    ["fatG", "Gorduras", "g"]
  ]) {
    const metric = document.createElement("div");
    const name = document.createElement("dt");
    name.textContent = label;
    const amount = document.createElement("dd");
    const value = nutrition.perServing[key];
    amount.textContent = Number.isFinite(value)
      ? nutritionNumber.format(value) + " " + unit
      : "Indisponível";
    metric.append(name, amount);
    values.append(metric);
  }

  const notes = document.createElement("p");
  notes.className = "nutrition-notes";
  if (nutrition.omissions?.length) {
    notes.append("O cálculo exclui " + nutrition.omissions.join(", ") + ". ");
  }
  if (nutrition.choices?.length) {
    notes.append("Versão calculada com " + nutrition.choices.join(", ") + ". ");
  }
  const source = document.createElement("a");
  source.href = nutrition.sourceUrl;
  source.textContent = nutrition.source;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  notes.append(source);
  container.append(title, values, notes);
}

function recipeCard(recipe, primary = false) {
  const card = recipeTemplate.content.firstElementChild.cloneNode(true);
  card.classList.toggle("recipe-card--primary", primary);
  card.querySelector("h3").textContent = recipe.title;

  const details = [];
  if (Number.isFinite(recipe.score)) details.push(recipe.score + "% dos ingredientes principais");
  if (recipe.prepTimeMinutes) details.push(recipe.prepTimeMinutes + " min");
  if (recipe.servings) details.push(recipe.servings + (recipe.servings === 1 ? " porção" : " porções"));
  const summary = card.querySelector(".recipe-summary");
  summary.textContent = details.join(" · ");
  summary.hidden = details.length === 0;

  const source = card.querySelector(".recipe-source");
  source.href = recipe.sourceUrl;
  source.setAttribute("aria-label", "Ver preparo de " + recipe.title + " na fonte");
  card.querySelector("[data-field='matched']").textContent =
    recipe.matchedIngredients?.join(", ") || "Nenhum item reconhecido";
  card.querySelector("[data-field='missing']").textContent =
    recipe.missingIngredients?.join(", ") || "Nenhum ingrediente principal";
  renderNutrition(card.querySelector(".recipe-nutrition"), recipe.nutrition);
  return card;
}

function appendResponse(data) {
  const { article, body } = createMessage(data.reply);
  const [primary, ...alternatives] = data.recipes ?? [];
  if (primary) {
    article.classList.add("message-with-recipes");
    body.append(recipeCard(primary, true));
  }
  if (alternatives.length) {
    const details = document.createElement("details");
    details.className = "recipe-alternatives";
    const summary = document.createElement("summary");
    summary.textContent = alternatives.length === 1 ? "Ver outra receita" : "Ver outras " + alternatives.length + " receitas";
    details.append(summary, ...alternatives.map((recipe) => recipeCard(recipe)));
    body.append(details);
  }
  messages.append(article);
  bringIntoView(article, true);
}

function appendError(message, timedOut) {
  const { article, body } = createMessage(timedOut
    ? "A busca demorou demais."
    : "Não foi possível buscar receitas.");
  article.classList.add("message-error");
  retryButton = document.createElement("button");
  retryButton.type = "button";
  retryButton.className = "text-button";
  retryButton.textContent = "Tentar novamente";
  retryButton.addEventListener("click", () => {
    if (pending) return;
    if (document.activeElement === retryButton) messages.focus({ preventScroll: true });
    retryButton = null;
    article.remove();
    requestResponse(message);
  });
  body.append(retryButton);
  messages.append(article);
  bringIntoView(article, true);
}

function setSending(sending) {
  for (const button of [submitButton, ...promptButtons]) {
    if (sending) button.setAttribute("aria-disabled", "true");
    else button.removeAttribute("aria-disabled");
  }
}

async function requestResponse(message) {
  const controller = new AbortController();
  pending = controller;
  setSending(true);
  const timeout = setTimeout(() => controller.abort(), 25_000);

  const { article: loading } = createMessage("Buscando receitas…");
  loading.classList.add("message-loading");
  messages.append(loading);
  bringIntoView(loading);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message, state: conversationState }),
      signal: controller.signal
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    if (pending !== controller) return;
    loading.remove();
    appendResponse(data);
    conversationState = data.state;
  } catch {
    if (pending === controller) {
      loading.remove();
      appendError(message, controller.signal.aborted);
    }
  } finally {
    clearTimeout(timeout);
    if (pending === controller) {
      pending = null;
      setSending(false);
    }
  }
}

function sendMessage(text, fromComposer = false) {
  const message = text.trim();
  if (pending || !message) return;

  retryButton?.remove();
  retryButton = null;
  if (fromComposer) input.value = "";
  messages.append(createMessage(message, true).article);
  requestResponse(message);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (pending) return;
  if (!input.value.trim()) {
    input.setCustomValidity("Digite os ingredientes que você tem.");
    input.reportValidity();
    return;
  }
  sendMessage(input.value, true);
});

input.addEventListener("input", () => input.setCustomValidity(""));
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

promptButtons.forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});

clearButton.addEventListener("click", () => {
  pending?.abort();
  pending = null;
  conversationState = null;
  retryButton = null;
  setSending(false);
  messages.replaceChildren(initialMessage.cloneNode(true));
  input.value = "";
  input.setCustomValidity("");
  input.focus({ preventScroll: true });
});
