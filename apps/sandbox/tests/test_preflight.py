from yearbook_sandbox.preflight import find_forbidden_token


def test_whole_word_tokens_only():
    assert find_forbidden_token("import socket") == "socket"
    assert find_forbidden_token("from subprocess import run") == "subprocess"
    assert find_forbidden_token("x = ctypes.CDLL(None)") == "ctypes"
    assert find_forbidden_token("os.system('ls')") == "os.system"
    assert find_forbidden_token("importlib.import_module('os')") == "importlib"
    assert find_forbidden_token("__import__('os')") == "__import__"


def test_benign_code_passes():
    code = (
        "import json, os\n"
        "import pandas as pd\n"
        "websocket_count = 3  # contains the token as a substring only\n"
        "print(os.listdir('/work/in'))\n"
    )
    assert find_forbidden_token(code) is None
