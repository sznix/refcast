# Hero GIF Recording Guide

Goal: 6-second animated GIF demonstrating refcast failover.

## Storyboard

1. **Frame 1 (0–2s)** — Terminal split-pane.
   - Left: `await research("What was Q3 revenue?", corpus_id="cor_x")`
   - Result streams; show `backend_used: "gemini_fs"` + 3 citations with `[1] [2] [3]`
2. **Frame 2 (2–4s)** — Config diff animates:
   ```diff
   - preferred_backend: "gemini_fs"
   + preferred_backend: "exa"
   ```
3. **Frame 3 (4–6s)** — Same query reruns. Result streams with `backend_used: "exa"`. **Citation JSON byte-identical** in shape.

Caption text: **"Cast once. Cite anywhere."**

## Recording

### Option A — `asciinema` + `agg`

```bash
brew install asciinema
cargo install --git https://github.com/asciinema/agg
asciinema rec hero.cast --idle-time-limit 0.5 --rows 24 --cols 100
# ... do the demo ...
agg --speed 1.5 hero.cast docs/hero.gif
```

### Option B — OBS + `ffmpeg`

```bash
# Record 1080p screen capture in OBS, then:
ffmpeg -i hero.mov -vf "fps=15,scale=1080:-1" docs/hero.gif
```

## Quality bar

- Under 2 MB
- Caption text legible at 800px width (GitHub render width)
- Loops cleanly
- Final frame freezes on caption
