factorial() returns the wrong number

`factorial(5)` should be 120 but returns 24. It looks like the loop stops one
factor early.

Repro: test_mathutil.py::test_factorial
