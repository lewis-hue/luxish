/**
 * Stand-in for a bundled image.
 *
 * Metro turns `require('…/x.webp')` into an opaque numeric handle; jest has no
 * asset pipeline, so without this every module that registers a cover fails to
 * resolve and whole test files disappear rather than failing visibly.
 *
 * A number, because that is what the real thing is, and `hasCover` and friends
 * only ever check that one exists.
 */
module.exports = 1;
