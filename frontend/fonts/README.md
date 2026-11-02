# Studio fonts

The user supplied references for expressive display serifs. The application uses
**Cormorant Garamond** for headings and **Manrope** for body text and controls as
open-source alternatives with complete Ukrainian alphabet coverage. These are
not the exact New York or other fonts pictured in the references.

Both families are distributed under the SIL Open Font License 1.1. The original
copyright notices and licenses are included alongside the fonts.

Official source files from the Google Fonts repository:

- https://github.com/google/fonts/tree/main/ofl/cormorantgaramond
- https://github.com/google/fonts/tree/main/ofl/manrope

The upstream variable TTFs were converted without subsetting to WOFF2 using
FontTools 4.68.0 (`TTFont`, `font.flavor = "woff2"`, `font.save(...)`). Full Latin
and Cyrillic coverage is retained, including Ґ/ґ, Є/є, І/і and Ї/ї. Runtime font
downloads use only the application's own `/static/fonts/` paths; no Google Fonts
network access is needed by the browser.

Loading uses `font-display: swap`; Georgia and system sans-serif are the fallbacks.
This conversion tooling is not an application runtime dependency.
