import catalog from "../data/recipes.json" with { type: "json" };

const ALIASES = {
  abobrinha: ["abobrinhas"],
  acucar: ["acucares"],
  alho: ["alhos"],
  "alho poro": ["alho frances"],
  arroz: ["arrozes"],
  aveia: ["aveia em flocos", "aveia em flocos finos", "flocos de aveia"],
  azeite: ["azeite de oliva", "azeite extra virgem"],
  banana: ["bananas", "banana nanica", "bananas nanicas", "banana prata", "banana nanina"],
  batata: ["batatas", "batata inglesa"],
  "batata doce": ["batatas doces"],
  cacau: ["cacau em po", "cacau em po 100"],
  cebola: ["cebolas"],
  cenoura: ["cenouras"],
  cogumelo: ["cogumelos"],
  "creme de leite": ["creme de leite com soro", "creme de leite sem soro"],
  ovo: ["ovos", "ovo inteiro", "ovos inteiros", "clara de ovo", "claras de ovo", "gema de ovo", "gemas de ovo"],
  "farinha de trigo": ["trigo", "farinha de trigo peneirada"],
  feijao: ["feijoes"],
  frango: ["peito de frango", "file de peito de frango", "file de frango", "files de frango", "frango desfiado"],
  iogurte: ["iogurte natural", "iogurte desnatado"],
  leite: ["leite integral", "leite desnatado", "leite semidesnatado"],
  limao: ["limoes"],
  macarrao: ["massa de macarrao"],
  milho: ["milho verde", "milho verde escorrido"],
  mussarela: ["mucarela", "mozarela", "queijo mussarela", "queijo mucarela"],
  oleo: ["oleo de soja", "oleo vegetal"],
  peixe: ["file de peixe", "files de peixe"],
  pimentao: ["pimentoes"],
  queijo: ["queijos", "queijo ralado"],
  "fermento quimico": ["fermento", "fermento em po", "fermento quimico em po"],
  tapioca: ["goma de tapioca"],
  tomate: ["tomates"],
  "tomate cereja": ["tomates cereja"],
  "molho de tomate": ["molho de tomate pronto"]
};

const GROUPS = {
  laticinios: /\b(?:leite(?! de (?:coco|soja|aveia|amendoas?|arroz|castanha))|queijo|mussarela|requeijao|iogurte|manteiga(?! de amendoim)|nata|soro de leite|parmesao|ricota|cream cheese|lactose|whey|coalhada|provolone|gorgonzola)\b/,
  carne: /\b(?:carne|boi|bovino|bacon|linguica|presunto|pernil|costela|salame|calabresa|ac[eé]m|patinho|picanha|maminha|alcatra|mortadela|porco|suino|file mignon|bife|contrafile|contra file|lombo)\b/,
  aves: /\b(?:frango|galinha|chester|peru|coxa|sobrecoxa|tender)\b/,
  peixe: /\b(?:peixe|atum|sardinha|salmao|tilapia|bacalhau|merluza|merlin|pescada|cacao|anchova|linguado|corvina|robalo|panga)\b/,
  "frutos do mar": /\b(?:camarao|camaroes|lula|polvo|marisco|ostra|mexilhao|siri|lagosta|surimi|kani|caranguejo)\b/,
  glúten: /\b(?:trigo|gluten|cevada|centeio|seitan|farinha de rosca|panko|pao|macarrao|massa de lasanha|massa de pastel|biscoito|aveia(?! certificada))\b/
};
const DIETS = {
  vegetariano: ["carne", "aves", "peixe", "frutos do mar"],
  vegano: ["carne", "aves", "peixe", "frutos do mar", "laticinios", "ovo", "mel", "gelatina", "banha", "maionese"]
};
const PANTRY = new Set(["sal", "sal grosso", "agua", "agua fervendo", "agua morna"]);
const QUALIFIERS = /^(?:(?:cozid[oa]s?|assad[oa]s?|cru[ao]s?|desfiad[oa]s?|temperad[oa]s?|organicos?|organicas?|peneirad[oa]s?|fresc[oa]s?|em cubos|em fatias|em pedacos|em rodelas|congelad[oa]s?)\s*)+$/;
const EXCLUSION_ALIASES = {
  "laticinio": "laticinios", "laticinios": "laticinios", "lactose": "laticinios",
  "gluten": "glúten", "frutos do mar": "frutos do mar", "aves": "aves", "carnes": "carne"
};

export function fold(value) {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().match(/[a-z0-9]+/g)?.join(" ") ?? "";
}

const aliases = new Map(Object.entries(ALIASES).flatMap(([canonical, names]) =>
  [canonical, ...names].map((name) => [name, canonical])));
const longestAliases = [...aliases.keys()].sort((a, b) => b.length - a.length);

function canonicalIngredient(value) {
  const name = fold(value);
  const alias = longestAliases.find((candidate) => name === candidate ||
    (name.startsWith(candidate + " ") && QUALIFIERS.test(name.slice(candidate.length + 1))));
  return alias ? aliases.get(alias) : name;
}

const recipes = catalog.map((recipe) => ({
  ...recipe,
  ingredients: recipe.ingredients.map((item) => ({
    ...item,
    keys: [...new Set(item.name.split(/\s+ou\s+/).map(canonicalIngredient))],
    optional: PANTRY.has(item.name) || /\bopcional\b/i.test(item.original)
  }))
}));

const ingredientKeys = new Set(recipes.flatMap((recipe) => recipe.ingredients.flatMap(({ keys }) => keys)));
const vocabulary = new Map([...ingredientKeys].filter(Boolean).map((key) => [key, key]));
for (const [name, key] of aliases) {
  vocabulary.set(name, key);
}
for (const [name, key] of Object.entries(EXCLUSION_ALIASES)) {
  vocabulary.set(name, key);
}
const phrase = [...vocabulary.keys()].sort((a, b) => b.length - a.length).join("|");
const ingredientPattern = new RegExp("\\b(?:" + phrase + ")\\b", "g");
const markerPattern = /\b(?:(?<absent>nao (?:tenho|possuo|temos)|falta|acabou)|(?<excluded>sem|evito|evite|nao (?:quero|como|posso comer)|alergi[ac][ao]?s? (?:a|ao))|(?<available>tenho|possuo|temos|sobrou|tambem|mais))\b/g;
const restrictions = new Set([...ingredientKeys, ...vocabulary.values(), ...Object.keys(GROUPS)]);

function listed(values, allowed) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.slice(0, 24).filter((value) => allowed.has(value)))];
}

export function validateState(input) {
  return {
    available: listed(input?.available, ingredientKeys),
    unavailable: listed(input?.unavailable, ingredientKeys),
    excluded: listed(input?.excluded, restrictions),
    diet: Object.hasOwn(DIETS, input?.diet) ? input.diet : null,
    maxMinutes: Number.isInteger(input?.maxMinutes) && input.maxMinutes > 0 && input.maxMinutes <= 1440
      ? input.maxMinutes : null,
    quick: input?.quick === true,
    budget: input?.budget === true
  };
}

export function readMessage(message, previousInput) {
  const previous = validateState(previousInput);
  const text = fold(message);
  const updates = { available: new Set(), unavailable: new Set(), excluded: new Set() };
  for (const segment of message.split(/[.!?;\n]+/).map(fold)) {
    const markers = [...segment.matchAll(markerPattern)];
    for (const item of segment.matchAll(ingredientPattern)) {
      const key = vocabulary.get(item[0]);
      const marker = markers.findLast((entry) => entry.index < item.index);
      const kind = marker ? Object.keys(marker.groups).find((group) => marker.groups[group]) : "available";
      if (kind === "excluded") {
        updates.excluded.add(key);
      } else if (ingredientKeys.has(key)) {
        const list = kind === "absent" ? "unavailable" : "available";
        updates[list === "available" ? "unavailable" : "available"].delete(key);
        updates[list].add(key);
      }
    }
  }

  const resetPantry = /\b(?:so tenho|somente tenho|apenas tenho|tenho so|tenho apenas)\b/.test(text);
  const continuation = /\b(?:tambem|alem disso|acrescente|adicione|mais|sobrou|e se)\b/.test(text);
  const reusePantry = !resetPantry && (continuation || updates.available.size === 0);
  const available = [
    ...(reusePantry ? previous.available : []),
    ...updates.available
  ].filter((key) => !updates.unavailable.has(key));
  const unavailable = [
    ...(reusePantry ? previous.unavailable : []),
    ...updates.unavailable
  ].filter((key) => !updates.available.has(key));
  const time = text.match(/\b(?:ate|no maximo|menos de|so tenho|tenho apenas)\s+(\d{1,4})\s*(?:minutos?|min)\b/);
  const statedTime = time ? Number(time[1]) - Number(time[0].startsWith("menos de")) : null;
  const diet = /\bvegan[oa]\b/.test(text) ? "vegano"
    : /\bvegetarian[oa]\b/.test(text) ? "vegetariano" : previous.diet;

  return validateState({
    available,
    unavailable,
    excluded: [...updates.excluded, ...previous.excluded],
    diet,
    maxMinutes: statedTime ?? previous.maxMinutes,
    quick: previous.quick || /\b(?:rapid[oa]s?|depressa|sem demora)\b/.test(text),
    budget: previous.budget || /\b(?:barat[oa]s?|economi[cz][oa]s?|baixo custo|custo baixo)\b/.test(text)
  });
}

function matchesExclusion(item, term) {
  const group = GROUPS[term];
  if (group) return group.test(item.name) || group.test(fold(item.original));
  if (item.keys.includes(term)) return true;
  if (term === "leite") return GROUPS.laticinios.test(item.name);
  if (term === "queijo") return /\b(?:queijo|mussarela|requeijao|parmesao|ricota|provolone|gorgonzola)\b/.test(item.name);
  if (term === "tomate" && item.keys.includes("tomate cereja")) return true;
  return (" " + item.name + " ").includes(" " + term + " ");
}

export function rankRecipes(state) {
  const excluded = new Set([...state.excluded, ...(DIETS[state.diet] ?? [])]);
  const available = new Set(state.available);
  const results = [];
  for (const recipe of recipes) {
    if (recipe.ingredients.some((item) => [...excluded].some((term) => matchesExclusion(item, term)))) continue;
    if (state.maxMinutes && (!recipe.prepTimeMinutes || recipe.prepTimeMinutes > state.maxMinutes)) continue;
    const essential = recipe.ingredients.filter(({ optional }) => !optional);
    const matched = essential.filter(({ keys }) => keys.some((key) => available.has(key)));
    if (!matched.length) continue;
    const missing = essential.filter((item) => !matched.includes(item));
    const coverage = matched.length / essential.length;
    const preferenceBonus =
      (state.quick && recipe.prepTimeMinutes ? Math.max(0, 1 - recipe.prepTimeMinutes / 60) * 0.18 : 0) +
      (state.budget && fold(recipe.cost ?? "") === "custo baixo" ? 0.12 : 0);
    results.push({
      recipe,
      rankScore: coverage + Math.min(matched.length, 6) * 0.04 - missing.length * 0.035 + preferenceBonus,
      card: {
        id: recipe.id,
        title: recipe.title,
        sourceUrl: recipe.sourceUrl,
        prepTimeMinutes: recipe.prepTimeMinutes,
        servings: recipe.servings,
        cost: recipe.cost,
        nutrition: recipe.nutrition ?? null,
        matchedIngredients: matched.map(({ label }) => label),
        missingIngredients: missing.map(({ label }) => label),
        score: Math.round(100 * coverage)
      }
    });
  }
  return results.sort((a, b) => b.rankScore - a.rankScore ||
    a.card.missingIngredients.length - b.card.missingIngredients.length ||
    a.card.id.localeCompare(b.card.id));
}

export function ruleReply(state, results) {
  if (results.length) {
    const first = results[0].card;
    const count = first.missingIngredients.length;
    const description = count === 0 ? "Você já tem todos os ingredientes principais."
      : "Entre os ingredientes principais, " + (count === 1 ? "falta um item." : "faltam " + count + " itens.");
    return "Minha sugestão é " + first.title + ". " + description;
  }
  return state.available.length
    ? "Não encontrei uma receita que combine com os ingredientes e as condições informadas. Você tem mais algum ingrediente?"
    : "Quais ingredientes você tem em casa? Pode mandar uma lista, por exemplo: arroz, tomate e ovo.";
}
