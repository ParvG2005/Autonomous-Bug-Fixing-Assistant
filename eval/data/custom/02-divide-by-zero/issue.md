divide by zero crashes

`divide(1, 0)` raises instead of returning 0.

Traceback (most recent call last):
  File "calc.py", line 5, in divide
    return a / b
ZeroDivisionError: division by zero

Repro: test_calc.py::test_divide_by_zero
