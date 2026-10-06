# Font provenance

Retrieved 2026-10-06 from the official [Google Fonts repository](https://github.com/google/fonts), pinned to commit [`7085eb89a950e85db5b166b7a58d414544b4140c`](https://github.com/google/fonts/commit/7085eb89a950e85db5b166b7a58d4140c).

## Sources and licenses

- Anek Telugu source: `ofl/anektelugu/AnekTelugu[wdth,wght].ttf` (SHA-256 `25981968a8a3faab975993a54eec455829214390821037fb3a4d6c447d2e1179`); copyright The Anek Project Authors. License: [SIL Open Font License 1.1](OFL-AnekTelugu.txt), copied as `OFL-AnekTelugu.txt` beside both web and native assets.
- Manrope source: `ofl/manrope/Manrope[wght].ttf` (SHA-256 `3ae11c49db0455a3cc33e37d380f20fdb8c7f8b41dc07625c177e3d87a9d6ae6`); copyright The Manrope Project Authors. License: [SIL Open Font License 1.1](OFL-Manrope.txt), copied as `OFL-Manrope.txt` beside both web and native assets.
- Neither OFL file declares a specific `Reserved Font Name`. Upstream family names are retained.

## Generated files

The web outputs are variable WOFF2: Anek Telugu retains `wght` 100–800 and `wdth` 75–125 (default width 100); Manrope retains `wght` 200–800. Native outputs are four actual static TTF instances per family at weights 400, 500, 600, and 700. Anek Telugu instances set `wdth=100`; the weights are instantiated from the variable font and are not synthetic bold styles.

Generation used isolated local tools in `work/font-tools`: fontTools 4.65.0 and Brotli 1.2.0. No application dependency was added.

All native Anek Telugu weights map 88 Unicode codepoints in U+0C00–U+0C7F and cover the verification sample `తెలుగు భాషా పరీక్ష`. Metadata and weight tables were verified for every static font; web WOFF2 axes were inspected after conversion. This verifies character coverage, not visual rendering or shaping; web/native screenshot QA is separate.

| Output | Bytes | SHA-256 |
|---|---:|---|
| `static/fonts/AnekTelugu-Variable.woff2` | 516,616 | `b7d76a8751213faee0d981217db18ecc309efa38bb793c966ccd7c0458b841a1` |
| `static/fonts/Manrope-Variable.woff2` | 53,668 | `75cb8f6131bf1c0df878b2e665fa56fa94ba0215ad94f854d4deb329853f7570` |
| `mobile/assets/fonts/AnekTelugu-400.ttf` | 320,136 | `05ecf8f3af72c14096f757f1ed728c3a0a90ede75d8f2befe5f831a1e0ec8d5e` |
| `mobile/assets/fonts/AnekTelugu-500.ttf` | 320,024 | `961e0bb8cff24338db26f4a72eb7ca947d3a63d7eefd5da9af940b3fa17dae5b` |
| `mobile/assets/fonts/AnekTelugu-600.ttf` | 320,808 | `1a204a53f13a5c0df055c546c8687dc1f66258f41c5778f92a6b7f38b28e8eff` |
| `mobile/assets/fonts/AnekTelugu-700.ttf` | 322,084 | `cc4fb19b6a89fb137b9bfc676cf8ff0e8f58f79570dcc3ab2d5003c1862001fc` |
| `mobile/assets/fonts/Manrope-400.ttf` | 97,584 | `f08f2927e22ac6845aa03a12e2374b098b798a83c2f26e344aaacea32ca2f835` |
| `mobile/assets/fonts/Manrope-500.ttf` | 97,644 | `8c75b77d02bfcc246f0ec14e26579acb55c130df2be621cb3eab3f01f1d106dc` |
| `mobile/assets/fonts/Manrope-600.ttf` | 97,692 | `3ab68716167eec0a20effb19104edfe2d051790f98bf46361049b0befc041241` |
| `mobile/assets/fonts/Manrope-700.ttf` | 97,568 | `0374ae8939ac70f24304bd0e7983c5f5ff689f7f3ad486df17c884a51614bc6e` |
