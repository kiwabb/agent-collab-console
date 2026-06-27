#!/usr/bin/env bash
# Phase 5: mypy baseline burn-down helper.
#
# This script demonstrates the "one module at a time" approach for
# tightening mypy strict on the 94-module app/ surface without exploding
# the PR diff. The pattern is:
#
#   1. Add the target module(s) to the strict list in pyproject.toml's
#      [[tool.mypy.overrides]].
#   2. Run `mypy app` and read the new errors.
#   3. Fix them (or accept the diff in this PR).
#   4. Re-run; once a module is 0-error it stays in the strict list.
#
# The modules listed below are the Phase 3 / Phase 4 modules that were
# written fresh under `from __future__ import annotations` with explicit
# type hints. They should pass strict = true with zero overrides.
set -euo pipefail

cd "$(dirname "$0")/../backend"

.venv/bin/mypy --strict --explicit-package-bases \
  app/application/conductor_state_machine.py \
  app/interfaces/common.py 2>&1 | tee /tmp/mypy_burndown.log
