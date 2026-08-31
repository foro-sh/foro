import assert from 'node:assert/strict'
import { test } from 'node:test'

import { manifestCases } from './manifest-cases.js'

// Sanity checks on the shared table itself - the generator
// (scripts/generate-manifest-cases.mjs) already enforces these invariants at
// build time, but that only runs when someone builds this package locally.
// A real `.test.ts` here means CI catches a malformed table on every push,
// not just when a maintainer happens to run `npm run build`.

test('manifestCases is non-empty', () => {
  assert.ok(manifestCases.length > 0)
})

test('every case name is unique', () => {
  const names = manifestCases.map((c) => c.name)
  assert.equal(new Set(names).size, names.length)
})

test('every case has files to write and a well-formed expect', () => {
  for (const testCase of manifestCases) {
    assert.ok(Object.keys(testCase.files).length > 0, `${testCase.name}: no files`)
    if (testCase.expect.ok) continue
    assert.ok(
      typeof testCase.expect.reason === 'string' && testCase.expect.reason.length > 0,
      `${testCase.name}: missing rejection reason`,
    )
  }
})
