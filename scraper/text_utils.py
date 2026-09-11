from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup


WHITESPACE_RE = re.compile(r"\s+")
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
PREPARATION_PIPELINE_VERSION = "pln-aula-5-v1"
PREPARATION_TRANSFORMATIONS = (
    "html_residual_removed",
    "urls_removed",
    "spaces_normalized",
    "casefolded",
    "accents_removed",
    "punctuation_and_symbols_removed",
    "word_tokenized",
    "pt_stopwords_removed_with_negation_preserved",
    "light_portuguese_stemming",
    "heuristic_portuguese_lemmatization",
)

PORTUGUESE_STOPWORDS = {
    "a",
    "ao",
    "aos",
    "aquela",
    "aquelas",
    "aquele",
    "aqueles",
    "aquilo",
    "as",
    "ate",
    "com",
    "como",
    "da",
    "das",
    "de",
    "dela",
    "delas",
    "dele",
    "deles",
    "depois",
    "do",
    "dos",
    "e",
    "ela",
    "elas",
    "ele",
    "eles",
    "em",
    "entre",
    "era",
    "eram",
    "essa",
    "essas",
    "esse",
    "esses",
    "esta",
    "estao",
    "estar",
    "estas",
    "estava",
    "estavam",
    "este",
    "estes",
    "eu",
    "foi",
    "foram",
    "ha",
    "isso",
    "isto",
    "ja",
    "lhe",
    "lhes",
    "mais",
    "mas",
    "me",
    "mesmo",
    "minha",
    "minhas",
    "meu",
    "meus",
    "muito",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "pela",
    "pelas",
    "pelo",
    "pelos",
    "por",
    "porque",
    "qual",
    "quando",
    "que",
    "quem",
    "se",
    "seja",
    "ser",
    "seu",
    "seus",
    "sua",
    "suas",
    "tambem",
    "tem",
    "tendo",
    "ter",
    "teu",
    "teus",
    "tua",
    "tuas",
    "um",
    "uma",
    "umas",
    "uns",
    "voce",
    "voces",
}

LEXICAL_LEMMAS = {
    "adicione": "adicionar",
    "adicionar": "adicionar",
    "adicionando": "adicionar",
    "batatas": "batata",
    "cebolas": "cebola",
    "colheres": "colher",
    "cozinhe": "cozinhar",
    "cozinhar": "cozinhar",
    "cozinhando": "cozinhar",
    "dentes": "dente",
    "deixe": "deixar",
    "deixar": "deixar",
    "fatie": "fatiar",
    "ferva": "ferver",
    "ferver": "ferver",
    "gramas": "grama",
    "ingredientes": "ingrediente",
    "misture": "misturar",
    "misturar": "misturar",
    "misturando": "misturar",
    "minutos": "minuto",
    "pique": "picar",
    "porcoes": "porcao",
    "receitas": "receita",
    "refogue": "refogar",
    "refogar": "refogar",
    "tomates": "tomate",
    "xicara": "xicara",
    "xicaras": "xicara",
}

STEM_SUFFIXES = (
    "amentos",
    "imentos",
    "adoras",
    "adores",
    "acoes",
    "icoes",
    "mente",
    "ando",
    "endo",
    "indo",
    "aria",
    "eria",
    "iria",
    "cao",
    "dor",
    "das",
    "dos",
    "ais",
    "oes",
    "res",
    "es",
    "as",
    "os",
    "s",
)


@dataclass(frozen=True)
class PreparedText:
    raw_text: str
    clean_text: str
    normalized_text: str
    tokens: list[str]
    content_tokens: list[str]
    stemmed_tokens: list[str]
    lemma_tokens: list[str]
    duplicate_key: str
    near_duplicate_key: str
    pipeline_version: str = PREPARATION_PIPELINE_VERSION
    transformations: tuple[str, ...] = PREPARATION_TRANSFORMATIONS


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return WHITESPACE_RE.sub(" ", html.unescape(value)).strip()


def remove_html_residual(value: str | None) -> str:
    text = clean_text(value)
    if not text or not HTML_TAG_RE.search(text):
        return text
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    return clean_text(soup.get_text(" ", strip=True))


def remove_urls(value: str | None) -> str:
    return clean_text(URL_RE.sub(" ", clean_text(value)))


def normalize_text(value: str | None) -> str:
    value = clean_text(value).casefold()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def remove_punctuation_and_symbols(value: str | None) -> str:
    text = clean_text(value)
    characters: list[str] = []
    for character in text:
        category = unicodedata.category(character)
        if category.startswith("P") or category in {"Sc", "Sk", "Sm", "So"}:
            characters.append(" ")
        else:
            characters.append(character)
    return clean_text("".join(characters))


def normalize_lexical(value: str | None) -> str:
    text = remove_html_residual(value)
    text = remove_urls(text)
    text = normalize_text(text)
    text = remove_punctuation_and_symbols(text)
    return clean_text(text)


def tokenize_words(value: str | None) -> list[str]:
    return TOKEN_RE.findall(normalize_lexical(value))


def remove_stopwords(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in PORTUGUESE_STOPWORDS]


def stem_token(token: str) -> str:
    for suffix in STEM_SUFFIXES:
        if len(token) - len(suffix) >= 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def lemmatize_token(token: str) -> str:
    if token in LEXICAL_LEMMAS:
        return LEXICAL_LEMMAS[token]
    if len(token) > 5 and token.endswith("oes"):
        return f"{token[:-3]}ao"
    if len(token) > 5 and token.endswith("ais"):
        return f"{token[:-3]}al"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def prepare_text(value: str | None) -> PreparedText:
    raw_text = "" if value is None else str(value)
    clean = remove_urls(remove_html_residual(raw_text))
    normalized = normalize_lexical(clean)
    tokens = tokenize_words(normalized)
    content_tokens = remove_stopwords(tokens)
    stemmed_tokens = _stable_unique([stem_token(token) for token in content_tokens])
    lemma_tokens = _stable_unique([lemmatize_token(token) for token in content_tokens])
    duplicate_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    near_duplicate_key = hashlib.sha256(" ".join(sorted(set(content_tokens))).encode("utf-8")).hexdigest()
    return PreparedText(
        raw_text=raw_text,
        clean_text=clean,
        normalized_text=normalized,
        tokens=tokens,
        content_tokens=content_tokens,
        stemmed_tokens=stemmed_tokens,
        lemma_tokens=lemma_tokens,
        duplicate_key=duplicate_key,
        near_duplicate_key=near_duplicate_key,
    )


def search_index_text(values: list[str]) -> str:
    prepared = prepare_text(" ".join(value for value in values if value))
    return " ".join(
        _stable_unique(
            [
                *prepared.tokens,
                *prepared.content_tokens,
                *prepared.stemmed_tokens,
                *prepared.lemma_tokens,
            ]
        )
    )


def search_terms(value: str | None) -> list[str]:
    prepared = prepare_text(value)
    terms = _stable_unique([*prepared.lemma_tokens, *prepared.stemmed_tokens])
    if terms:
        return terms
    return _stable_unique(prepared.content_tokens or prepared.tokens)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def parse_localized_number(value: str | None) -> int | None:
    if not value:
        return None
    text = clean_text(value).casefold().replace(" ", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1].replace(",", ".")
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1].replace(",", ".")
    else:
        text = re.sub(r"[^0-9]", "", text)
        return int(text) if text else None
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def parse_rating(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[,.]\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_minutes(value: str | None) -> int | None:
    if not value:
        return None
    text = clean_text(value).casefold()
    hours = re.search(r"(\d+)\s*h", text)
    minutes = re.search(r"(\d+)\s*(?:min|m)\b", text)
    if not hours and not minutes:
        return None
    return (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)


def site_recipe_id_from_url(url: str) -> str | None:
    match = re.search(r"/receita/(\d+)(?:[-/.?]|$)", urlsplit(url).path + ("?" if "?" in url else ""))
    return match.group(1) if match else None


def site_category_id_from_url(url: str) -> str | None:
    match = re.search(r"/categorias/([^/?#]+)", urlsplit(url).path)
    if not match:
        return None
    numeric = re.match(r"\d+", match.group(1))
    return numeric.group(0) if numeric else match.group(1)

