# Image Processing Studio — visual identity

## Direction
Luxury minimalism × modern creative studio. The UI must feel refined, clean, professional, and highly usable. References supplied by the user: five Pantone-inspired images depicting blueberries/navy, rose-gold metal, coconut-white textures, olive fruit, and dark purple/plum. Reference images are mood/color inspiration, **not** backgrounds to copy or assets licensed for redistribution.

## Color tokens (approximate screen-friendly interpretations, not official Pantone conversions)
| Role | Name | Hex |
|---|---|---|
| Primary dark surface | Neon Navy | `#131936` |
| Accent | Rose Gold | `#B77E72` |
| Light base | Coconut Milk | `#F0EEE6` |
| Secondary accent | Olive Green | `#4B5409` |
| Deep secondary | Potent Purple | `#29101F` |
| Navy hover/lighter surface | Navy Elevated | `#202849` |
| Light card | Soft Ivory | `#FBFAF6` |
| Dark text on light | Ink | `#1D2336` |
| Muted light text | Muted Ivory | `#DDDCD9` |
| Outline | Soft Outline | `#DAD7D0` |

## Application rules
- Default to a clean, **light work canvas** in Coconut Milk/Soft Ivory, with a strong Neon Navy left sidebar/topbar. This lets photographs remain the visual focus.
- Rose Gold for primary buttons, progress bars, active selection highlights, and focus rings; ensure readable contrast with dark text and accessible control states.
- Olive Green reserved for success/completed labels and small data accents; Potent Purple for secondary cards, charts, or important dark accents, not broad random decorations.
- Avoid gradients, metallic effects, textures, photos-as-background, and Pantone branding throughout the functional dashboard unless deliberately requested.
- Typography: modern neutral sans-serif, e.g. system UI / Inter if available; sensible typography hierarchy, generous spacing, rounded corners 12–16px, restrained shadow.
- Screens: upload workspace (drag & drop), processing settings, job progress/status, history, result download, login, and admin monitoring. Responsive desktop/mobile layouts.
- States: QUEUED neutral, RUNNING Rose Gold, COMPLETED Olive, FAILED error red with accessible contrast, CANCELLED muted neutral. Never depend on color alone.
- Use actual text labels and icons for clarity. High-contrast accessible form controls and visible keyboard focus.

## Suggested layout
Desktop: navy navigation at left, off-white working surface on right, large file upload area, processing controls and latest job card with fine navy borders and rose-gold action. Mobile: stacked content and compact top navigation.

## References
Reference files provided by user can be used for inspiration only. When integrating visual assets, store them in a separate `design-references/` folder locally and do not display the moodboard images on the actual website by default.
