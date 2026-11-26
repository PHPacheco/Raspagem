const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const submitButton = form.querySelector("button[type='submit']");
const clearButton = document.querySelector("#clear-chat");
const recipeTemplate = document.querySelector("#recipe-template");
const initialMessage = messages.innerHTML;

let history = [];

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
    data.recipes.forEach((recipe, index) => {
      const card = recipeTemplate.content.firstElementChild.cloneNode(true);
      card.querySelector(".recipe-number").textContent = String(index + 1).padStart(2, "0");
      card.querySelector("h3").textContent = recipe.title;
      card.querySelector(".match-score").textContent = `${recipe.score ?? 0}% compatível`;
      const details = [recipe.prepTimeMinutes && `${recipe.prepTimeMinutes} min`,
        recipe.servings && `${recipe.servings} ${recipe.servings === 1 ? "porção" : "porções"}`];
      card.querySelector(".recipe-summary").textContent = details.filter(Boolean).join(" · ");
      card.querySelector(".recipe-source").href = recipe.sourceUrl;
      card.querySelector("[data-field='matched']").textContent =
        recipe.matchedIngredients?.join(", ") || "nenhum item reconhecido";
      card.querySelector("[data-field='missing']").textContent =
        recipe.missingIngredients?.join(", ") || "nada essencial";
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

async function requestRecipes(message) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, history: history.slice(-6) })
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function sendMessage(message) {
  const trimmed = message.trim();
  if (!trimmed) return;

  appendUserMessage(trimmed);
  history.push({ role: "user", content: trimmed });
  input.value = "";
  submitButton.disabled = true;
  appendTyping();

  try {
    const data = await requestRecipes(trimmed);
    appendBotResponse(data);
    history.push({ role: "assistant", content: data.reply });
  } catch {
    appendError();
  } finally {
    submitButton.disabled = false;
    input.focus();
  }
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

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});

clearButton.addEventListener("click", () => {
  history = [];
  messages.innerHTML = initialMessage;
  input.value = "";
  input.focus();
});
