import pytest

from scripts.url_segura import url_portal_valida


@pytest.mark.parametrize(
    "url",
    [
        "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/x.cpe?id=1",
        "https://compraspublicas.gob.ec/x",
        "HTTPS://WWW.COMPRASPUBLICAS.GOB.EC/x",
        "https://www.compraspublicas.gob.ec:443/x",
    ],
)
def test_urls_del_portal_se_aceptan(url):
    assert url_portal_valida(url)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://www.compraspublicas.gob.ec/x",  # sin TLS
        "https://evil.example.com/x",
        "https://www.compraspublicas.gob.ec.evil.com/x",  # sufijo enganoso
        "https://evilcompraspublicas.gob.ec/x",
        "https://www.compraspublicas.gob.ec@evil.com/x",  # el host real es evil.com
        "https://user:pass@www.compraspublicas.gob.ec/x",
        "https://www.compraspublicas.gob.ec:8443/x",
        "https://127.0.0.1/x",
        "https://localhost:8000/api/todos",
        "http://169.254.169.254/latest/meta-data",  # metadatos cloud
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "//www.compraspublicas.gob.ec/x",
        123,
    ],
)
def test_urls_fuera_de_lista_blanca_se_rechazan(url):
    assert not url_portal_valida(url)
