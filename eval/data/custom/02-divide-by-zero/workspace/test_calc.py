from calc import add, divide


def test_divide_by_zero():
    assert divide(1, 0) == 0


def test_add_ok():
    assert add(2, 3) == 5
