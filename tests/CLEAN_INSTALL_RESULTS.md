# Clean installation verification — v0.4.28 release gate

The clean-install workflow exports the committed tree, creates a fresh virtual
environment, installs the package with test/image/audio/websocket/MCP extras,
and verifies that imports come from site-packages rather than the source tree.
The v0.4.28 pre-release clean-install run produced **228 passed, 1 skipped** on
Python 3.11; the release workflow repeats the check on Python 3.10, 3.11 and
3.12 before it can upload assets. The skip is the private Pirates
page-classification evidence that is not distributed with the repository. These
tests exercise installation and software behavior; they do not establish desktop
audio quality or universal transcription accuracy.

The verified native editor platform remains macOS / MuseScore Studio 4.7.4.
Windows core package tests are a required CI gate; the Windows plugin and special
notation harness is reported separately as diagnostic evidence while its hosted
runner teardown behavior is stabilized.

## Historical baseline

The September 15, 2026 v0.1-era result was 73 passed and 1 skipped after fixes
to canonical instrument names. That result is retained here as historical context;
it is not the current release verification count.
