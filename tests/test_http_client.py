import pytest

from scraper.http_client import AcademicHttpClient, RecipeAuthorizationRequired


class FakeSession:
    def __init__(self) -> None:
        self.headers = {}
        self.calls: list[str] = []

    def mount(self, *_args) -> None:
        pass

    def get(self, url, **_kwargs):
        self.calls.append(url)
        raise AssertionError("A fixture de autorização não deveria fazer requisições neste teste")

    def close(self) -> None:
        pass


def test_recipe_access_is_denied_by_default_before_network_call() -> None:
    session = FakeSession()
    client = AcademicHttpClient(session=session, delay_seconds=0)

    with pytest.raises(RecipeAuthorizationRequired):
        client.fetch("https://www.tudogostoso.com.br/receita/1438-teste.html", resource_kind="recipe")

    assert session.calls == []


def test_robots_override_requires_explicit_authorization() -> None:
    with pytest.raises(ValueError):
        AcademicHttpClient(override_robots_with_permission=True)

