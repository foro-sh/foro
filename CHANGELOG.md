## [0.10.0](https://github.com/foro-sh/foro/compare/v0.9.3...v0.10.0) (2026-08-13)

## <small>0.9.3 (2026-08-07)</small>

* style: trim the commentary added across this branch ([fb8a4ac](https://github.com/foro-sh/foro/commit/fb8a4ac))
* fix(python): make failed handshakes raise HandshakeError on 3.10 ([9abb91a](https://github.com/foro-sh/foro/commit/9abb91a))
* fix(python): narrow hosts.yml to 0600 even when it already existed ([279160e](https://github.com/foro-sh/foro/commit/279160e))
* fix(python): only append /mcp to a URL that has no path of its own ([25fb67b](https://github.com/foro-sh/foro/commit/25fb67b))
* fix(python): poll the device endpoint before sleeping, not after ([ab2f62c](https://github.com/foro-sh/foro/commit/ab2f62c))
* fix(python): read auth responses as shapes rather than trusting them ([ef8890d](https://github.com/foro-sh/foro/commit/ef8890d))
* fix(python): reject path segments that start with a dash ([d43ae88](https://github.com/foro-sh/foro/commit/d43ae88)), closes [#605](https://github.com/foro-sh/foro/issues/605) [#605](https://github.com/foro-sh/foro/issues/605)
* fix(python): report a missing uv or git instead of raising FileNotFoundError ([598e989](https://github.com/foro-sh/foro/commit/598e989))
* fix(python): stop `auth login --with-token` eating the token as a prompt answer ([8b9a626](https://github.com/foro-sh/foro/commit/8b9a626))
* fix(python): stop foro dev waiting on a server that already died ([2775e06](https://github.com/foro-sh/foro/commit/2775e06))
* fix(python): stop foro.run() silently ignoring an explicit port ([2b3cf79](https://github.com/foro-sh/foro/commit/2b3cf79))
* fix(python): stop the fastmcp import scan reading vendored code ([a0a7486](https://github.com/foro-sh/foro/commit/a0a7486))
* fix(python): survive a non-interactive stdin during auth login ([88b3abb](https://github.com/foro-sh/foro/commit/88b3abb))
* fix(typescript): run the test suite on a glob node 18 can expand ([db35a83](https://github.com/foro-sh/foro/commit/db35a83))
* chore(typescript): keep compiled tests out of the published package ([45b1f14](https://github.com/foro-sh/foro/commit/45b1f14))
* ci: block a release on a red test suite ([bcbabf6](https://github.com/foro-sh/foro/commit/bcbabf6))
* docs: fix typo ([991df9b](https://github.com/foro-sh/foro/commit/991df9b))

## <small>0.9.2 (2026-08-04)</small>

* fix(ci): install packages/typescript deps before the release build ([d1151ff](https://github.com/foro-sh/foro/commit/d1151ff)), closes [foro-sh/foro#49](https://github.com/foro-sh/foro/issues/49)
* fix(typescript): add the @types/node dev dependency node:test needs ([5b980a6](https://github.com/foro-sh/foro/commit/5b980a6))
* test(typescript): wire up the first real manifest-cases test ([d637a3d](https://github.com/foro-sh/foro/commit/d637a3d))

## <small>0.9.1 (2026-08-04)</small>

* test(python): cover manifest_path and is_valid_repo_path directly ([eacca34](https://github.com/foro-sh/foro/commit/eacca34))
* fix(python): close build_path/manifest_path validation gap ([52609ae](https://github.com/foro-sh/foro/commit/52609ae))

## 0.9.0 (2026-08-01)

* feat(python): show foro's banner instead of FastMCP's on startup (#45) ([d36d5e0](https://github.com/foro-sh/foro/commit/d36d5e0)), closes [#45](https://github.com/foro-sh/foro/issues/45)
* fix(python): make scaffolded tool registration hard to break silently (#44) ([96bd892](https://github.com/foro-sh/foro/commit/96bd892)), closes [#44](https://github.com/foro-sh/foro/issues/44)
* ci: run the Python and TypeScript test suites (#47) ([9d827dc](https://github.com/foro-sh/foro/commit/9d827dc)), closes [#47](https://github.com/foro-sh/foro/issues/47)

## <small>0.8.1 (2026-08-01)</small>

* fix(ci): relock the minimal-fastmcp fixture on release (#46) ([ecd297f](https://github.com/foro-sh/foro/commit/ecd297f)), closes [#46](https://github.com/foro-sh/foro/issues/46)

## 0.8.0 (2026-08-01)

* fix(python): address the Docker dev stack over plain HTTP too ([058eb3f](https://github.com/foro-sh/foro/commit/058eb3f))
* fix(python): poll on the interval slow_down sends back ([c40226c](https://github.com/foro-sh/foro/commit/c40226c))
* fix(python): remove hosts.yml when the last login goes ([6c7fd68](https://github.com/foro-sh/foro/commit/6c7fd68))
* fix(python): revoke the real token on logout, by prefix lookup ([ca8de02](https://github.com/foro-sh/foro/commit/ca8de02)), closes [platform#574](https://github.com/platform/issues/574)
* fix(python): show the same token prefix /account does ([b0796b4](https://github.com/foro-sh/foro/commit/b0796b4))
* feat(python): add credential storage and a stdlib HTTP layer ([f6ef6f7](https://github.com/foro-sh/foro/commit/f6ef6f7))
* feat(python): add foro auth login/status/logout/token ([3d77947](https://github.com/foro-sh/foro/commit/3d77947)), closes [foro-sh/foro#30](https://github.com/foro-sh/foro/issues/30) [foro-sh/platform#551](https://github.com/foro-sh/platform/issues/551)
* feat(python): reject a malformed --with-token before sending it ([73d2ad8](https://github.com/foro-sh/foro/commit/73d2ad8))
* docs(python): document foro auth in the package README ([be14d8c](https://github.com/foro-sh/foro/commit/be14d8c))

## 0.7.0 (2026-08-01)

* feat(python): add foro verify ([5947564](https://github.com/foro-sh/foro/commit/5947564))
* refactor(python): extract the MCP handshake out of dev ([ea531e3](https://github.com/foro-sh/foro/commit/ea531e3))

## 0.6.0 (2026-08-01)

* feat(python): add foro.bridge() stdio subprocess proxy ([1b58eed](https://github.com/foro-sh/foro/commit/1b58eed)), closes [#8](https://github.com/foro-sh/foro/issues/8)

## <small>0.5.2 (2026-07-31)</small>

* fix(plugin): point the docs MCP at the deployed server ([113ca47](https://github.com/foro-sh/foro/commit/113ca47))

## <small>0.5.1 (2026-07-31)</small>

* fix(python): pin mcp below 2.0 so uvx foro dev works ([5625184](https://github.com/foro-sh/foro/commit/5625184))

## 0.5.0 (2026-07-29)

* feat(plugin): add the foro Codex plugin with docs MCP and shared skills ([cf3466f](https://github.com/foro-sh/foro/commit/cf3466f))

## 0.4.0 (2026-07-29)

* docs(plugin): run foro init with --yes in the skills ([a277ac8](https://github.com/foro-sh/foro/commit/a277ac8))
* feat(python): add --yes to foro init ([649b04c](https://github.com/foro-sh/foro/commit/649b04c))

## 0.3.0 (2026-07-29)

* feat(plugin): foro Claude Code plugin — docs MCP + create/deploy skills (#21) ([1b726f0](https://github.com/foro-sh/foro/commit/1b726f0)), closes [#21](https://github.com/foro-sh/foro/issues/21)

## <small>0.2.1 (2026-07-29)</small>

* fix(python): make `uvx foro init` work without the cli extra ([4cb45e1](https://github.com/foro-sh/foro/commit/4cb45e1))
* ci: authenticate npm publishes with trusted publishing ([b635aa7](https://github.com/foro-sh/foro/commit/b635aa7))
* ci: relock uv.lock when stamping the release version ([b14228f](https://github.com/foro-sh/foro/commit/b14228f))
* ci: route every npm publish through the release workflow ([da95042](https://github.com/foro-sh/foro/commit/da95042))
* ci: stop setup-node writing an npmrc that suppresses npm OIDC ([fa938b5](https://github.com/foro-sh/foro/commit/fa938b5))

## 0.2.0 (2026-07-29)

* feat(typescript): publish the shared manifest-cases table on npm ([4e21f2c](https://github.com/foro-sh/foro/commit/4e21f2c)), closes [foro-sh/foro#5](https://github.com/foro-sh/foro/issues/5)
* ci: publish each SDK on merge when its package changed, and pin releases to 0.x ([aa1341c](https://github.com/foro-sh/foro/commit/aa1341c))

## 1.4.0 (2026-07-20)

* feat(python): add foro init + foro dev (#15) ([30885b8](https://github.com/foro-sh/foro/commit/30885b8)), closes [#15](https://github.com/foro-sh/foro/issues/15) [foro-sh/foro#5](https://github.com/foro-sh/foro/issues/5) [foro-sh/foro#6](https://github.com/foro-sh/foro/issues/6) [foro-sh/foro#6](https://github.com/foro-sh/foro/issues/6) [#948](https://github.com/foro-sh/foro/issues/948)

## 1.3.0 (2026-07-20)

* feat(python): add foro check + shared manifest test fixtures ([f1e97a3](https://github.com/foro-sh/foro/commit/f1e97a3))

## 1.2.0 (2026-07-20)

* feat(python): add foro.run() runtime shim and foro.secret() helper ([864797c](https://github.com/foro-sh/foro/commit/864797c))

## 1.1.0 (2026-07-20)

* feat(python): add foro CLI entry point with check/init/dev stubs ([2512608](https://github.com/foro-sh/foro/commit/2512608))

## 1.0.0 (2026-07-20)

* fix(ci): correct broken commit-sha pins for third-party actions ([46804cc](https://github.com/foro-sh/foro/commit/46804cc))
* ci: add semantic release workflow ([b16bfde](https://github.com/foro-sh/foro/commit/b16bfde))
* ci: add semantic-release workflow and expand gitignore ([43bd000](https://github.com/foro-sh/foro/commit/43bd000))
* ci: pin github actions to commit shas ([1c4d5c7](https://github.com/foro-sh/foro/commit/1c4d5c7))
* refactor(npm): use scoped package @foro-sh/foro ([2c53946](https://github.com/foro-sh/foro/commit/2c53946))
* docs(commits): add instructions on how to write commit messages ([545b80e](https://github.com/foro-sh/foro/commit/545b80e))
* Add pypi environment to Python publish workflow ([0875238](https://github.com/foro-sh/foro/commit/0875238))
* Initialize SDK monorepo scaffolding ([a788f82](https://github.com/foro-sh/foro/commit/a788f82))
