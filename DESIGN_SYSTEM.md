# Image Processing Studio — visual identity

## Direction
Luxury minimalism × modern creative studio. The UI must feel refined, clean, professional, and highly usable. The user updated the direction to olive, dark navy and burgundy, with expressive display serif typography inspired by the supplied New York and display-font references. Reference images are mood/color inspiration, **not** backgrounds or font files licensed for redistribution.

## Color tokens (approximate screen-friendly interpretations, not official Pantone conversions)
| Role | Name | Hex |
|---|---|---|
| Primary dark surface | Neon Navy | `#131936` |
| Primary action / display accent | Burgundy | `#632D3D` |
| Light base | Coconut Milk | `#F0EEE6` |
| Primary processing action / active navigation | Olive Green | `#4B5409` |
| Olive light surface | Olive Soft | `#E9EBD9` |
| Navy hover/lighter surface | Navy Elevated | `#202849` |
| Light card | Soft Ivory | `#FBFAF6` |
| Dark text on light | Ink | `#1D2336` |
| Muted light text | Muted Ivory | `#DDDCD9` |
| Outline | Soft Outline | `#DAD7D0` |

## Application rules
- Default to a clean, **light work canvas** in Coconut Milk/Soft Ivory, with a strong Neon Navy left sidebar/topbar. This lets photographs remain the visual focus.
- Burgundy for account actions, headline accents and focus rings. Olive for processing/download actions, active navigation, upload/connection surfaces and completed labels. Navy anchors the sidebar and secondary controls. Ivory text on dark controls; dark text on pale surfaces.
- Rose Gold and Potent Purple are superseded by the user's new palette. Theme tokens in `frontend/theme.css` remain the source of truth.
- Avoid gradients, metallic effects, textures, photos-as-background, and Pantone branding throughout the functional dashboard unless deliberately requested.
- Typography: locally hosted Cormorant Garamond variable (300–700) for headings/IPS and Manrope variable (200–800) for body text and controls. Both include the complete Ukrainian alphabet. Use `--font-display` and `--font-body`; fall back to Georgia and system sans-serif. Large display headings, readable form labels, generous spacing and restrained corners.
- These are open-source alternatives inspired by the references, not the exact New York/other pictured fonts. Exact originals require the user's font files and appropriate licenses. Do not guess download sources for commercial fonts. Preserve the OFL licenses bundled in `frontend/fonts`.
- Screens: upload workspace (drag & drop), processing settings, job progress/status, history, result download, login, and admin monitoring. Responsive desktop/mobile layouts.
- States: QUEUED neutral, RUNNING Burgundy, COMPLETED Olive, FAILED error red with accessible contrast, CANCELLED muted neutral. Never depend on color alone.
- Use actual text labels and icons for clarity. High-contrast accessible form controls and visible keyboard focus.

## Suggested layout
Desktop: navy navigation at left, off-white working surface on right, large file upload area, processing controls and latest job card with fine navy borders and rose-gold action. Mobile: stacked content and compact top navigation.

## References
Reference files provided by user can be used for inspiration only. When integrating visual assets, store them in a separate `design-references/` folder locally and do not display the moodboard images on the actual website by default.
