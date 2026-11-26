const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const submitButton = form.querySelector("button[type='submit']");
const clearButton = document.querySelector("#clear-chat");
const recipeTemplate = document.querySelector("#recipe-template");
const initialMessage = messages.innerHTML;

const promptButtons = [...document.querySelectorAll("[data-prompt]")];
let conversationState = null;
let pending = null;

function appendUserMessage(text) {
  const article = document.createElement("article");
  article.className = "message message-user";
  const body = document.createElement("div");
  body.className = "message-body";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.append(paragraph);
  article.append(body);
  messages.append(article);
}

function appendTyping() {
  const article = document.createElement("article");
  article.className = "message message-bot";
  article.dataset.typing = "true";
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "PA";
  const body = document.createElement("div");
  body.className = "message-body";
  const indicator = document.createElement("div");
  indicator.className = "typing";
  indicator.setAttribute("aria-label", "Procurando receitas");
  indicator.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
  body.append(indicator);
  article.append(avatar, body);
  messages.append(article);
  scrollToLatest();
}

const nutritionNumber = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

function renderNutrition(card, nutrition) {
  const caption = card.querySelector(".recipe-nutrition");
  if (!nutrition) {
    caption.textContent = "Estimativa nutricional indisponível.";
    return;
  }

  const values = [
    ["caloriesKcal", "kcal", "calorias"],
    ["proteinG", "g de proteínas", "proteínas"],
    ["carbohydratesG", "g de carboidratos", "carboidratos"],
    ["fatG", "g de gorduras", "gorduras"]
  ].map(([key, unit, label]) => {
    const value = nutrition.perServing[key];
    return Number.isFinite(value)
      ? nutritionNumber.format(value) + " " + unit
      : label + " indisponíveis";
  });
  caption.textContent = "Estimativa por porção · " + values.join(" · ") + ". ";
  if (nutrition.omissions.length) {
    caption.append("O cálculo exclui " + nutrition.omissions.join(", ") + ". ");
  }
  if (nutrition.choices.length) {
    caption.append("Versão calculada com " + nutrition.choices.join(", ") + ". ");
  }
  const source = document.createElement("a");
  source.href = nutrition.sourceUrl;
  source.textContent = nutrition.source;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  caption.append(source);
}

function appendBotResponse(data) {
  messages.querySelector("[data-typing='true']")?.remove();

  const article = document.createElement("article");
  article.className = "message message-bot";
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "PA";
  const body = document.createElement("div");
  body.className = "message-body";
  const paragraph = document.createElement("p");
  paragraph.textContent = data.reply;
  body.append(paragraph);

  if (Array.isArray(data.recipes) && data.recipes.length) {
    const list = document.createElement("div");
    list.className = "recipe-list";
    data.recipes.forEach((recipe) => {
      const card = recipeTemplate.content.firstElementChild.cloneNode(true);
      card.querySelector("h3").textContent = recipe.title;
      card.querySelector(".match-score").textContent = `${recipe.score ?? 0}% dos ingredientes principais`;
      const details = [recipe.prepTimeMinutes && `${recipe.prepTimeMinutes} min`,
        recipe.servings && `${recipe.servings} ${recipe.servings === 1 ? "porção" : "porções"}`];
      card.querySelector(".recipe-summary").textContent = details.filter(Boolean).join(" · ");
      card.querySelector(".recipe-source").href = recipe.sourceUrl;
      card.querySelector("[data-field='matched']").textContent =
        recipe.matchedIngredients?.join(", ") || "nenhum item reconhecido";
      card.querySelector("[data-field='missing']").textContent =
        recipe.missingIngredients?.join(", ") || "nada essencial";
      renderNutrition(card, recipe.nutrition);
      list.append(card);
    });
    body.append(list);
  }

  article.append(avatar, body);
  messages.append(article);
  scrollToLatest();
}

function appendError() {
  messages.querySelector("[data-typing='true']")?.remove();
  appendBotResponse({
    reply: "Não consegui processar a mensagem agora. Tente novamente em alguns instantes.",
    recipes: []
  });
}

function scrollToLatest() {
  messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
}

async function requestRecipes(message, signal) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, state: conversationState }),
    signal
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function sendMessage(message) {
  const trimmed = message.trim();
  if (!trimmed || pending) return;

  const controller = new AbortController();
  pending = controller;
  setSending(true);

  appendUserMessage(trimmed);
  input.value = "";
  appendTyping();

  try {
    const data = await requestRecipes(trimmed, controller.signal);
    if (pending !== controller) return;
    conversationState = data.state;
    appendBotResponse(data);
  } catch {
    if (pending === controller) appendError();
  } finally {
    if (pending === controller) {
      pending = null;
      setSending(false);
      input.focus();
    }
  }
}

function setSending(sending) {
  submitButton.disabled = sending;
  promptButtons.forEach((button) => { button.disabled = sending; });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
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
  setSending(false);
  messages.innerHTML = initialMessage;
  input.value = "";
  input.focus();
});
