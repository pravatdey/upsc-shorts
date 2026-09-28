# UPSC Shorts — automated daily YouTube Shorts

Generates and uploads **3 vertical Shorts every morning** for civil services /
competitive exam prep — geopolitics, polity, economy, environment, history and
more — entirely from GitHub Actions. No machine of yours needs to be running.

Built on the same shape as `reasoning-mastery`, but rebuilt for the Shorts
format: 1080x1920, under 60 seconds, hook-first scripting, and word-synced
burned-in captions.

---

## What one video looks like

Seven beats, roughly 48 seconds:

| Beat | Time | Job |
|---|---|---|
| Hook | 0-5s | A question or contradiction that stops the scroll |
| Background | 5-12s | One idea: why this matters |
| Fact 1-3 | 12-35s | The surprising, exam-relevant substance |
| Exam point | 35-42s | How UPSC actually asks this |
| CTA | 42-48s | Engagement question, then follow |

Every frame carries a big headline, a live caption band where the word being
spoken is highlighted, a top progress bar and beat dots. The accent colour
changes per category, so three Shorts posted the same morning don't look like
one repeated template.

---

## How it works

```
config/topics.yaml     160 topics, 10 categories
        |
        v
  TopicBank            pick 3 unused, spread across categories
        |
        v
  ScriptWriter         Groq (fallback: Gemini) -> 7 beats, word-budgeted
        |
        v
  TTSManager           Gemini TTS Hindi (fallback: Edge TTS) + word timings
        |
        v
  ShortComposer        1080x1920 cards + karaoke captions -> MP4
        |
        v
  YouTubeUploader      upload, thumbnail, first comment, playlist
        |
        v
  progress.json        committed back so tomorrow never repeats a topic
```

Two things are deliberately different from a long-form pipeline:

- **Narration length is the only real control on video length.** The script
  writer is given a hard word budget and trims overruns. If narration still
  lands over the limit, ffmpeg `atempo` nudges it back under 58s — crossing 60
  takes the video off the Shorts shelf entirely.
- **Frames are rendered from a single `make_frame`,** not stacked MoviePy
  clips. At this resolution a per-word caption overlay built from clips would
  hold hundreds of full-frame RGBA layers in memory at once.

---

## Setup

**New here? Follow [SETUP.md](SETUP.md)** — a step-by-step walkthrough from
zero to a running channel, with a check after every step. The summary below
assumes you already know the pieces.

### 1. Install

```bash
pip install -r requirements.txt
```

Windows already has a Devanagari font (Nirmala UI). On Linux:

```bash
sudo apt-get install -y ffmpeg libraqm0 fonts-noto-core
```

### 2. API keys

Copy `.env.example` to `.env` and fill it in. Both are free:

| Key | Used for | Get it |
|---|---|---|
| `GROQ_API_KEY` | Writing scripts | https://console.groq.com/keys |
| `GEMINI_API_KEY` | Hindi voice + script fallback | https://aistudio.google.com/apikey |

### 3. YouTube authorization (once)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project and enable **YouTube Data API v3**.
2. Credentials → Create OAuth client ID → **Desktop app** → download the JSON.
3. Save it as `config/client_secrets.json`.
4. Run:

```bash
python authorize_youtube.py
```

This opens a browser, then writes `config/youtube_token.json` and prints the
value you need for the `YOUTUBE_TOKEN` GitHub secret.

### 4. Check everything

```bash
python check_setup.py
```

Fix anything marked `FAIL` before going further.

### 5. Build one video locally

```bash
python main.py --count 1 --no-upload
```

The MP4 lands in `output/videos/`. **Watch it before enabling the schedule.**

---

## GitHub Actions

Add three repository secrets — *Settings → Secrets and variables → Actions*:

| Secret | Value |
|---|---|
| `GROQ_API_KEY` | your Groq key |
| `GEMINI_API_KEY` | your Gemini key |
| `YOUTUBE_TOKEN` | the entire contents of `config/youtube_token.json` |

Then push. The workflow runs daily at **06:00 IST** and can be triggered by
hand from the Actions tab with a video count, a private-upload toggle, and an
optional forced topic.

**Do your first CI run with `test_mode: true`.** It uploads as private, so you
can inspect the result on YouTube before anything goes public.

The workflow commits `progress.json` back to the repo after each run. That file
is how tomorrow's run knows which topics are already used — SQLite lives in
`data/`, which CI wipes on every run.

---

## Day-to-day

```bash
python main.py                    # today's batch of 3
python main.py --count 1          # just one
python main.py --no-upload        # build locally, upload nothing
python main.py --test             # upload as private
python main.py --topic geo-001    # force a specific topic
python main.py --status           # what's published, what's left
python main.py --list-topics      # the whole bank, used ones marked
```

---

## Tuning

Everything worth changing is in `config/settings.yaml`.

| Setting | Effect |
|---|---|
| `batch.videos_per_run` | Shorts per run. YouTube's API quota allows ~6/day |
| `script.language` | `hindi` or `english` — switches prompts, voice and fonts |
| `script.target_seconds` | Video length. Lower = punchier, better completion rate |
| `tts.gemini.voice_name` | `Fenrir`, `Charon`, `Puck` (male), `Kore`, `Zephyr` (female) |
| `tts.provider` | `edge` skips Gemini entirely — no quota, less natural |
| `video.preset` | `fast` for quicker CI runs, `slow` for smaller files |
| `youtube.privacy_status` | Set `private` while testing |
| `youtube.playlist_id` | Add every Short to a playlist |

**Adding topics** — append to `config/topics.yaml`. The `angle` field matters
most: it is the difference between "explain the Siachen Glacier" and "why India
spends crores to hold a glacier where nobody lives". Write the angle you would
click on.

**Branding** — `channel.brand` in settings sets the top-left text. Colours live
in `Palette.ACCENTS` in `src/video/theme.py`, one accent per category. To use
custom fonts, drop them at `assets/fonts/NotoSansDevanagari-Bold.ttf` and
`assets/fonts/Inter-Bold.ttf`; they take priority over system fonts.

---

## Troubleshooting

**Hindi text renders as boxes** — no Devanagari font. Install
`fonts-noto-core` (it ships `NotoSansDevanagari-Bold.ttf`), or drop a `.ttf`
into `assets/fonts/`.

**Hindi matras sit in the wrong place** (`डग्ि्री` instead of `डिग्री`) — Pillow
has no Raqm shaping engine. Common on Windows; `check_setup.py` warns about it.
GitHub Actions installs Raqm and fails the run if it is missing, so uploads are
unaffected — only local previews look wrong.

**Gemini TTS quota errors** — the free tier allows a few requests per minute.
Raise `batch.delay_between_videos_seconds`, or set `tts.provider: edge`.

**Upload succeeds but the video isn't a Short** — YouTube classifies by shape
and length, not by any API flag. It must be vertical and 60 seconds or less.
Check the duration in the run log.

**Thumbnail not applied** — custom thumbnails need a verified channel. The
upload still succeeds; only the thumbnail is skipped.

**A topic failed** — it is released back to the pool automatically and retried
on the next run. Nothing is silently skipped.

---

## Cost

Zero. Groq, Gemini and GitHub Actions free tiers cover a 3-video daily run
comfortably. A run takes roughly 10-15 minutes of Actions time.
