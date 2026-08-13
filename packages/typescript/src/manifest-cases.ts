/**
 * The shared `foro.yaml` validation table.
 *
 * foro's `_manifest.py` is a port of foro-sh/platform's
 * `apps/api/src/services/manifest.ts`, and the two can never be allowed to
 * silently disagree about what a valid manifest is - if they do, `foro check`
 * passes locally and the deploy fails, which is the exact gap this SDK exists
 * to close. Both sides therefore run the same table: the Python package
 * through `tests/test_manifest_cases.py`, the platform by importing
 * `manifestCases` from here (foro-sh/foro#5).
 *
 * The cases assert only accept/reject and the rejection reason - the resolved
 * defaults each implementation produces stay covered by its own tests.
 */

import { rawManifestCases } from './_generated-manifest-cases.js'

/** Mirrors `ManifestRejectionReason` in foro-sh/platform's `@foro/types`.
 *  Kept in sync deliberately: it is what makes a reason added on one side a
 *  compile error on the other. */
export type ManifestRejectionReason =
  | 'missing_manifest'
  | 'unsupported_language'
  | 'invalid_yaml'
  | 'invalid_shape'
  | 'invalid_name'
  | 'invalid_entrypoint'
  | 'invalid_build_path'
  | 'invalid_runtime'
  | 'invalid_runtime_version'
  | 'invalid_port'
  | 'invalid_dependency_manager'
  | 'unsupported_project'
  | 'unknown_field'

export interface ManifestCase {
  /** Stable identifier, unique across the table - use it as the test name. */
  readonly name: string
  /** Verbatim `foro.yaml` contents to validate. */
  readonly yaml: string
  readonly expect:
    | { readonly ok: true }
    | { readonly ok: false; readonly reason: ManifestRejectionReason }
}

export const manifestCases: readonly ManifestCase[] = rawManifestCases
