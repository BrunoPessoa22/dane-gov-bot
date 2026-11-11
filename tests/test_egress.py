import pytest

from danegov.egress import ProxyConfigError, parse_proxy, portal_proxy

URL = "http://user-PL-1:p%40ss%3Aword@p.example.net:80"


def test_parse_splits_credentials_for_playwright() -> None:
    proxy = parse_proxy(URL)
    assert proxy.playwright() == {
        "server": "http://p.example.net:80",
        "username": "user-PL-1",
        "password": "p@ss:word",
    }


def test_describe_never_shows_credentials() -> None:
    described = parse_proxy(URL).describe()
    assert described == "http://p.example.net:80"
    assert "user" not in described and "word" not in described


def test_proxy_without_credentials() -> None:
    assert parse_proxy("socks5://10.0.0.1:1080").playwright() == {
        "server": "socks5://10.0.0.1:1080"
    }


@pytest.mark.parametrize(
    "url",
    ["p.example.net:80", "ftp://p.example.net:21", "http://p.example.net", "http://:80"],
)
def test_bad_urls_are_rejected_without_echoing_them(url: str) -> None:
    with pytest.raises(ProxyConfigError) as error:
        parse_proxy(url)
    assert "p.example.net" not in str(error.value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_means_direct(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("DANE_GOV_PROXY", raising=False)
    else:
        monkeypatch.setenv("DANE_GOV_PROXY", value)
    assert portal_proxy() is None


def test_set_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DANE_GOV_PROXY", f"  {URL}\n")
    proxy = portal_proxy()
    assert proxy is not None and proxy.host == "p.example.net"
