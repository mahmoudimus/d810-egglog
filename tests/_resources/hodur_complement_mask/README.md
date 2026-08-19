# Hodur complementary-mask fixture

This provider-owned fixture is copied byte-for-byte from commit
`89aa91671536ceda035e224b6f8884a4c8726170`:

- Source: `samples/src/masm_probes/Hodur_ComplementMaskResidual.asm`
- Image: `samples/bins/hodur_egglog_probe.dll`
- Export: `Hodur_ComplementMaskResidual`
- Purpose: focused native evidence for
  `Sub_ComplementMaskHodurRule_1` after forward constant propagation is
  disabled.

The image is intentionally checked in as a small MASM-only PE. Its layout is
independent of `libobfuscated.dll`, so unrelated native fixture changes cannot
silently change this test's Hex-Rays expression.

## Integrity

The expected SHA-256 of `hodur_egglog_probe.dll` is:

```text
575aea3e22d2fba5be0587e408d497c629e1d6d673bef523f52d49087ff94026
```

The MASM source must define the exported symbol named above. The focused
system test checks both the image digest and the source/export contract before
decompilation.
