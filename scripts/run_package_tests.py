"""Run the package test suite with the Windows runner signal workaround."""
import os
import signal
import sys

import pytest


if os.name == 'nt':
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)


raise SystemExit(pytest.main(sys.argv[1:]))
