from calculator import divide


def test_divide_regular_numbers():
    assert divide(10, 2) == 5
    assert divide(7, 2) == 3.5


def test_divide_by_zero_returns_none():
    assert divide(10, 0) is None
