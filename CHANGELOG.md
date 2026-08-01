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
