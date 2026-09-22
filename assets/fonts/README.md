# Custom fonts

Drop font files here to override the system fonts. They take priority over
everything else, so this is how you give the channel its own look without
touching code.

| Filename | Used for |
|---|---|
| `NotoSansDevanagari-Bold.ttf` | Hindi headlines and captions |
| `Inter-Bold.ttf` | English text, labels, pills |

Other accepted names are listed in `src/video/fonts.py`.

Pick a **bold or heavy weight**. Shorts are watched on a phone, often outdoors,
and regular weights disappear against the background.

If you use a Devanagari font, check that it covers conjuncts properly — some
free fonts drop them and render `क्ष` as two separate letters.
