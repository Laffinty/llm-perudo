"""P0 脚手架冒烟测试。

存在的理由：仓库此前无任何测试，若不放置至少一个测试，``pytest`` 会以
「no tests collected」返回 exit code 5，导致 CI 门禁 G-test 误判为红。
"""

import perudo


def test_import_perudo_succeeds() -> None:
    """确认 ``perudo`` 包可导入，且 ``__version__`` 为非空字符串。"""
    assert isinstance(perudo.__version__, str)
    assert perudo.__version__ != ""


def test_package_metadata_matches_skeleton() -> None:
    """确认导入到的是本仓库的 perudo 包，而非同名第三方包。"""
    assert perudo.__name__ == "perudo"
    assert perudo.__version__ == "0.1.0"
