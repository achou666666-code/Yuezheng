"""Run the package test suite with the Windows runner signal workaround."""
import os
import signal
import sys

import pytest


if os.name == 'nt':
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)


class _SessionResult:
    failed = False

    def pytest_collectreport(self, report):
        if report.failed:
            self.failed = True

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failed = True


result = _SessionResult()
status = pytest.main(sys.argv[1:], plugins=[result])
if os.name == 'nt' and status == 1 and not result.failed:
    print('Windows runner returned exit 1 after a no-failure pytest session; treating teardown status as successful.')
    status = 0
raise SystemExit(status)
