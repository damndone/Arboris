# Workbench v1.8.9 C2 P1 integration gate

This record is bounded to the Foundation Integration worktree before the C2
lock commit. The product tip under test was the C1-derived merge tip
`e59602bc9b7441c05b754c7adfa8ddfcc513483d`; the future C2 candidate commit is
not included here.

## Composition

- Baseline: C1 exact SHA `993e9de428045c088a4902cfabf3dba632c5bf37`.
- P1 assembly input: `5fb3fa8280c555129e02e3b8ee1f0de7d94f3456`.
- Product runtime central cutover and Report central mount remain deferred to C3.
- Shared dependencies were linked with `scripts/link-shared-deps.sh`; the
  links are ignored worktree environment state and are not product changes.

## Results on the composed tip

1. C2 backend package/catalog/consumer/classification focused command:
   `266 passed, 1 warning`.
2. C2 frontend focused command after dependency linking:
   `3 files passed, 13 tests passed`.
3. Frontend typecheck: passed.
4. P0 composed regression command: `468 passed, 93 warnings in 63.91s`.
5. Backend `compileall -q backend/workbench tests`: passed.
6. `git diff --check`: passed.
7. Provider catalog and coverage:
   - catalog digest: `19578bf373bf09b8764cc98d8d53221496e5b6d9a78fe60147a86205a627ea6d`
   - coverage digest: `86161af4d6edf44df5474880375bc1da2733aeb48b0de96a3fe9d8fd9e1f72f9`
   - coverage rows: 15 total, 5 covered, 10 blocked.

## Recovered environment gates

- The first frontend attempt was blocked because the new worktree had no
  `frontend/node_modules` link and Vite could not resolve
  `@vitejs/plugin-react`. The repository dependency-link script fixed the
  environment; the focused frontend run and typecheck then passed.
- The first P0 attempt in the restricted sandbox produced `135 failed, 333
  passed, 52 warnings` because host authority/Unix socket probes raised
  `PermissionError: [Errno 1] Operation not permitted`. The identical command
  in the approved controlled-host environment passed with `468 passed, 93
  warnings`. The restricted result is not treated as a product regression.

## Boundary

This is package and composition evidence only. Browser acceptance, real
provider acceptance, production identity resolution, central Agent/Notebook
cutover, full host gate, and release/tag status remain `NOT_VERIFIED`.
