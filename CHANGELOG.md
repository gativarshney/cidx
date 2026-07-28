# Changelog

All notable changes to cidx are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once the first release exists. Until then, everything lands under Unreleased.

## [Unreleased]

### Added

- Installable package skeleton (src layout) with the `cidx` console entry point;
  `cidx --help` and `cidx --version` work after `pip install -e .`.
- CI matrix running ruff and pytest on {Ubuntu, macOS, Windows} x {Python 3.11, 3.12, 3.13}.
- Project documentation: README, ARCHITECTURE, DECISIONS, MILESTONES, AGENTS.
- Apache-2.0 license.
