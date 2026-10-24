# Upgrade notes: NetState Reconciler 0.2.0

## Why this upgrade exists

Version 0.2.0 prioritizes audit trustworthiness. A network audit must not appear fully clean when the parser silently skipped configuration that can affect routing or security, and a remediation planner must account for ordered ACL semantics.

## Changes

- Unknown interface and OSPF subcommands produce parser warnings.
- Selected security/routing-sensitive global configuration outside the modeled subset produces parser warnings, including local users, AAA, VTY/console line configuration, SSH management, SNMP, static routes, NAT, alternate routing protocols, and selected policy features.
- Common interface `duplex`, `speed`, `media-type`, and `load-interval` defaults are currently ignored because they are not managed by the desired-state schema. This is an explicit scope decision, not proof these values do not matter operationally.
- Audits with parser warnings report `INCOMPLETE (PARSER WARNINGS)` when there are no other drifts and exit nonzero; do not interpret them as compliant.
- IPv4 masks must be contiguous subnet masks.
- ACL bindings accept only `in`/`out` directions; numeric ACL identifiers are normalized to strings.
- Explicit YAML `null` can express the intended absence of supported nullable fields.
- Numbered ACL order-only differences produce a complete manual-review rebuild plan instead of an incomplete membership-only change.
- Test suite expanded from 13 to 23 tests.

## Apply the patch to an existing clone

1. Ensure important local changes are committed or backed up:

   ```bash
   cd ~/projects/netstate-reconciler
   git status --short
   ```

2. Download `NetState_Reconciler_v0.2.0_patch.zip` and merge its contents into the repository root (the archive paths start at the repo root):

   ```bash
   unzip -o ~/Downloads/NetState_Reconciler_v0.2.0_patch.zip -d .
   ```

3. Refresh the editable install and run tests:

   ```bash
   python -m pip install -e '.[dev]'
   pytest -v
   netstate --version
   ```

4. Review and commit the changes:

   ```bash
   git status --short
   git add .gitignore CHANGELOG.md Makefile README.md UPGRADE_NOTES_0.2.0.md \
     pyproject.toml src tests docs
   git commit -m "Improve parser safety and ACL remediation planning"
   git push
   ```

The patch does not include or overwrite `configs/router1-lab.yaml` or `live_configs/`, so your Packet Tracer lab specification and locally exported router snapshot remain in place. `live_configs/` is ignored by Git in this version.

## Important limitation

This release still models a bounded subset of Cisco IOS. The targeted global-command warnings are not an exhaustive detector for every unmodeled IOS feature. A clean audit describes only the declared fields and supported syntax; it is not proof of whole-device security or network reachability.
