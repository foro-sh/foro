/** Shared project-config validation table. Imported by foro-sh/platform. */

import { rawManifestCases } from './_generated-manifest-cases.js'

/** Mirrors `ManifestRejectionReason` in foro-sh/platform's `@foro/types`. */
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
  | 'invalid_egress'

export interface ManifestCase {
  readonly name: string
  readonly files: Readonly<Record<string, string>>
  readonly expect:
    | { readonly ok: true }
    | { readonly ok: false; readonly reason: ManifestRejectionReason }
}

export const manifestCases: readonly ManifestCase[] = rawManifestCases
