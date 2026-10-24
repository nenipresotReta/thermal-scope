# Contributing and publication readiness

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

Thermal Scope is currently a private project being prepared for external use. Project source is licensed under [MIT](LICENSE). Repository visibility is a separate owner decision.

## Before a change

Read the README and linked guides. Use synthetic data and placeholder configuration for tests. Keep runtime/build output outside tracked source. Include the commit, reproduction steps, expected/actual behavior and relevant test results when proposing a fix. Hardware results should name the tested board, sensor and toolchain; do not generalize them to untested variants.

Run the checks listed in the README before proposing a change. `tools/check_release.py` inspects the **Git index**, not all unstaged files or all past commits. Review and stage intended source changes before running it. Passing this scanner is not proof that all private information has been removed.

## Before making the repository public

- Review third-party code/asset provenance and dependency notices. Project MIT licensing does not replace dependency licenses or grant rights to third-party marks.
- Review every branch/tag and reachable Git history, plus release notes/assets, issues, CI logs/artifacts and any screenshots. Current-tree checks alone are insufficient.
- Exclude real network credentials, generated headers, compiled firmware, personal device identifiers, private paths, measurement records and diagnostic captures. Rotate exposed credentials if any were previously uploaded; deleting the latest file is insufficient.
- Reproduce setup from a clean checkout with documented dependencies and placeholder configuration, then test on the stated hardware/network. Distinguish host tests, firmware builds and actual hardware tests.
- Retain the known limitations in the README and release notes. Describe the tested scope and version, not an unconditional reliability guarantee.

Do not attach private configuration or full unreviewed support bundles to issues. Public visibility requires a separate explicit decision by the repository owner.
