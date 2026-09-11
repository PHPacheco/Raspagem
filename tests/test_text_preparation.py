from scraper.text_utils import prepare_text, search_terms


def test_prepare_text_preserves_raw_and_derives_clean_versions() -> None:
    prepared = prepare_text(
        '<nav>Menu do site</nav><p>NÃO gostei das cebolas!!! 😕 Veja https://example.test/receita</p>'
    )

    assert prepared.raw_text.startswith("<nav>")
    assert "Menu do site" not in prepared.clean_text
    assert "https://" not in prepared.clean_text
    assert prepared.normalized_text == "nao gostei das cebolas veja"
    assert "nao" in prepared.content_tokens
    assert "das" not in prepared.content_tokens
    assert "cebola" in prepared.lemma_tokens
    assert "cebol" in prepared.stemmed_tokens
    assert prepared.pipeline_version == "pln-aula-5-v1"
    assert "html_residual_removed" in prepared.transformations


def test_search_terms_use_derived_forms_without_requiring_the_original_plural() -> None:
    assert search_terms("cebolas") == ["cebola", "cebol"]

