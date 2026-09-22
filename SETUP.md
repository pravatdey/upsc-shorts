# Complete setup guide

From nothing to 3 Shorts uploading automatically every morning.

Work through the steps in order. Each one ends with a check you can run, so you
always know whether it worked before moving on.

---

## Where you are now

| | Status |
|---|---|
| Code written and tested | done |
| Pushed to GitHub | done — https://github.com/pravatdey/upsc-shorts |
| Workflow file in place | done |
| **API keys** | **todo — Step 1** |
| **YouTube token** | **todo — Step 2** |
| Local test run | todo — Step 3 |
| First upload | todo — Step 4 |

---

## Step 1 — API keys (10 minutes)

You need two. Both are free and take a minute each.

### 1a. Groq key — writes the scripts

1. Go to https://console.groq.com/keys
2. Sign in with Google
3. **Create API Key** → name it `upsc-shorts` → **Submit**
4. Copy it immediately. It starts with `gsk_` and is shown **only once**.

### 1b. Gemini key — the Hindi voice

1. Go to https://aistudio.google.com/apikey
2. **Create API key** → choose your project (or let it make one)
3. Copy it. It starts with `AIza`.

### 1c. Put them in two places

**On your PC** — open `.env` and paste after the `=`, no quotes, no spaces:

```
GROQ_API_KEY=gsk_your_actual_key_here
GEMINI_API_KEY=AIzaYour_actual_key_here
```

**Save the file** (Ctrl+S). `.env` is gitignored, so it never reaches GitHub.

**On GitHub** — the daily run cannot read your `.env`, so it needs its own copy.
Go to:

https://github.com/pravatdey/upsc-shorts/settings/secrets/actions/new

Add two secrets, one at a time. The names must match exactly:

| Name | Value |
|---|---|
| `GROQ_API_KEY` | the `gsk_...` key |
| `GEMINI_API_KEY` | the `AIza...` key |

### Check

```
python check_setup.py
```

`LLM key` and `TTS voice` should both say `PASS`.

---

## Step 2 — YouTube token (20 minutes)

This is the longest step. There is no "YouTube API key" to copy — you create an
OAuth client, then sign in once to mint a token.

### 2a. Create a Google Cloud project

1. Go to https://console.cloud.google.com/
2. Project dropdown (top left) → **New Project**
3. Name: `upsc-shorts` → **Create**
4. Wait for it to finish, then make sure it is the **selected** project

### 2b. Enable the YouTube API

1. Search bar at the top → type `YouTube Data API v3`
2. Click the result → **Enable**

### 2c. Configure the consent screen

Left menu → **APIs & Services** → **OAuth consent screen**

1. User type: **External** → **Create**
2. App name: `UPSC Shorts Uploader`
3. User support email: your Gmail
4. Developer contact email: your Gmail
5. **Save and Continue**
6. Scopes page → **Save and Continue** (skip it)
7. Test users page → **Save and Continue** (skip it)
8. **Back to Dashboard**

### 2d. Publish the app — do not skip this

On the OAuth consent screen, find **Publishing status** and click
**PUBLISH APP** → **Confirm**.

> **Why this matters.** While the app sits in *Testing*, Google expires the
> refresh token after **7 days**. Your channel would upload fine for a week and
> then silently stop, with a confusing `invalid_grant` error in the logs. In
> *In production* the token does not expire.
>
> Because the app is not Google-verified, you will see a
> "Google hasn't verified this app" warning when you sign in. That is normal
> for a personal app. Click **Advanced** → **Go to UPSC Shorts Uploader
> (unsafe)**. It is your own app; the warning only means Google has not
> reviewed it.

### 2e. Create the OAuth client

1. Left menu → **Credentials**
2. **+ Create Credentials** → **OAuth client ID**
3. Application type: **Desktop app** ← this exact type
4. Name: `upsc-shorts-desktop` → **Create**
5. In the popup, or from the download icon on the client's row, click
   **Download JSON**
6. Save the file as exactly:

```
c:\github\personal_projcets\Short_video\config\client_secrets.json
```

> Choosing **Web application** instead of Desktop is the most common mistake.
> It fails later with `redirect_uri_mismatch`. If that happens, delete the
> client and create a new one as Desktop app.

### 2f. Mint the token

```
python authorize_youtube.py
```

What happens:

1. A browser opens
2. Sign in with **the Google account that owns your YouTube channel**
3. The unverified-app warning appears → **Advanced** → **Go to ... (unsafe)**
4. Permissions page → **Continue** / **Allow**
5. The terminal prints your channel name and a long `{...}` line

### 2g. Add it to GitHub

Copy the entire `{...}` line the command printed — including both braces.

Go to https://github.com/pravatdey/upsc-shorts/settings/secrets/actions/new

| Name | Value |
|---|---|
| `YOUTUBE_TOKEN` | the whole `{...}` line |

### Check

```
python check_setup.py
```

`YouTube auth` should say `PASS` and show your channel name. **If the channel
name is wrong, stop** — you signed in with the wrong Google account. Delete
`config/youtube_token.json` and run `python authorize_youtube.py` again.

---

## Step 3 — Build one video locally

Never upload something you have not watched.

```
python main.py --count 1 --no-upload
```

Takes 2-4 minutes. The file appears at `output\videos\short_0001.mp4`.

**Watch it and check:**

- Is the Hindi text readable, with matras in the right place?
- Do the captions match what the voice is saying?
- Is it under 60 seconds?
- Does the hook make you want to keep watching?

If the Hindi looks wrong locally (`डग्ि्री` instead of `डिग्री`), that is the
known Windows font-shaping limitation — GitHub Actions renders it correctly.
Everything else you see is what viewers will see.

> **If this fails on your PC:** your Python is 3.14, and `moviepy` does not
> support it. Either install Python 3.11 and use a virtual environment, or skip
> this step and rely on the private test upload in Step 4 instead.

---

## Step 4 — First upload, private

1. Go to https://github.com/pravatdey/upsc-shorts/actions
2. Click **Daily UPSC Shorts** in the left sidebar
3. Click **Run workflow** (right side)
4. Set:
   - `count` = **1**
   - `test_mode` = **true** ← uploads as private
5. Click the green **Run workflow**

Takes 10-15 minutes. Watch the log by clicking into the run.

When it finishes, go to [YouTube Studio](https://studio.youtube.com) → Content.
Your Short is there as **Private**. Watch it on your phone — that is the real
test, since that is how everyone will see it.

Happy with it? Change its visibility to Public manually, or just let the daily
schedule take over.

---

## Step 5 — Go live

Nothing left to do. The workflow already runs every day at **06:00 IST**
(00:30 UTC) and uploads 3 public Shorts.

To change the count or the time, edit `.github/workflows/daily-shorts.yml`:

```yaml
- cron: '30 0 * * *'     # 06:00 IST. This is UTC, not IST.
```

and `config/settings.yaml`:

```yaml
batch:
  videos_per_run: 3
```

Commit and push, and the change takes effect on the next run.

---

## Daily commands

```
python main.py --status          what is published, what is left
python main.py --list-topics     the whole topic bank, used ones marked
python main.py --count 1         make one now
python check_setup.py            diagnose anything broken
```

---

## When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `YOUTUBE_TOKEN secret is not set` | Step 2g missed | Add the secret |
| `invalid_grant` after ~a week | App left in *Testing* | Step 2d — publish the app, then redo 2f and 2g |
| `redirect_uri_mismatch` | OAuth client is Web type | Step 2e — recreate as Desktop app |
| Wrong channel in `check_setup.py` | Signed in with the wrong account | Delete `config/youtube_token.json`, redo 2f |
| `RESOURCE_EXHAUSTED` from Gemini | Free TTS tier rate limit | Raise `batch.delay_between_videos_seconds`, or set `tts.provider: edge` |
| Hindi renders as empty boxes | No Devanagari font | Only affects local runs; CI installs one |
| Video is not treated as a Short | Longer than 60s | Lower `script.target_seconds` in settings |
| Thumbnail not applied | Channel not verified | Harmless — the upload still succeeds |

A failed topic is automatically released back into the pool and retried on the
next run, so nothing is silently skipped.

---

## What it costs

Nothing. Groq, Gemini and GitHub Actions free tiers all cover a 3-video daily
run. The repository is public, which means unlimited Actions minutes.

Your API keys live only in `.env` (gitignored) and GitHub Secrets (encrypted,
never printed in logs). The workflow only triggers on a schedule or by hand, so
no one else can run it against your account.
