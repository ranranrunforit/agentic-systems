#!/usr/bin/env python3
"""Run the full suite. `python3 run_tests.py`"""
import sys, unittest

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n" + "=" * 70)
    print(f"{result.testsRun} tests, {len(result.failures)} failures, "
          f"{len(result.errors)} errors")
    print("=" * 70)
    sys.exit(0 if result.wasSuccessful() else 1)
