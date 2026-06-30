from foro import hello_foro


def test_smoke():
    assert hello_foro("test") == "Hello, test from Foro"
