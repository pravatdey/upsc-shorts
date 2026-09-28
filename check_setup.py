"""
Pre-flight check. Run this before your first real upload:

    python check_setup.py

It verifies everything that can be verified without spending API calls:
dependencies, API keys, fonts, text shaping, the topic bank and the YouTube
token. Anything marked FAIL will break the daily run.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
results = []


def check(label, status, detail=""):
    results.append((status, label, detail))
    print(f"[{status}] {label}" + (f"  -  {detail}" if detail else ""))


def main() -> int:
    print("=== UPSC Shorts setup check ===\n")

    # --- dependencies ---
    import importlib
    for module, package in [
        ("PIL", "Pillow"), ("numpy", "numpy"), ("yaml", "pyyaml"),
        ("loguru", "loguru"), ("sqlalchemy", "SQLAlchemy"),
        ("moviepy.editor", "moviepy==1.0.3"), ("pydub", "pydub"),
        ("edge_tts", "edge-tts"), ("groq", "groq"),
        ("google.genai", "google-genai"),
        ("googleapiclient.discovery", "google-api-python-client"),
    ]:
        try:
            importlib.import_module(module)
            check(f"dependency {package}", PASS)
        except Exception as e:
            check(f"dependency {package}", FAIL,
                  f"{type(e).__name__} - run: pip install -r requirements.txt")

    print()

    # --- config ---
    import yaml
    try:
        with open("config/settings.yaml", encoding="utf-8") as f:
            settings = yaml.safe_load(f)
        language = settings["script"]["language"]
        check("config/settings.yaml", PASS,
              f"language={language}, "
              f"{settings['batch']['videos_per_run']} videos/run, "
              f"target {settings['script']['target_seconds']}s")
    except Exception as e:
        check("config/settings.yaml", FAIL, str(e))
        return 1

    try:
        from src.content.topic_bank import TopicBank
        bank = TopicBank(settings["topics"]["file"])
        from src.utils.progress_store import ProgressStore
        used = len(ProgressStore("progress.json").used_topic_ids)
        remaining = bank.total - used
        days = remaining // max(1, settings["batch"]["videos_per_run"])
        check("topic bank", PASS if remaining > 0 else WARN,
              f"{bank.total} topics, {remaining} unused (~{days} days left)")
    except Exception as e:
        check("topic bank", FAIL, str(e))

    print()

    # --- API keys ---
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if groq_key or gemini_key:
        check("LLM key", PASS,
              ("GROQ_API_KEY set" if groq_key else "") +
              (" + " if groq_key and gemini_key else "") +
              ("GEMINI_API_KEY set" if gemini_key else ""))
    else:
        check("LLM key", FAIL, "set GROQ_API_KEY and/or GEMINI_API_KEY in .env")

    if gemini_key:
        check("TTS voice", PASS, "Gemini TTS available (realistic Hindi)")
    else:
        check("TTS voice", WARN,
              "no GEMINI_API_KEY - will fall back to Edge TTS (robotic but free)")

    print()

    # --- fonts and shaping ---
    from PIL import features
    from src.video.fonts import FontBook
    book = FontBook()

    if book.devanagari_path:
        check("Devanagari font", PASS, book.devanagari_path)
    else:
        check("Devanagari font", FAIL if language == "hindi" else WARN,
              "install fonts-noto-core, or drop a .ttf at "
              "assets/fonts/NotoSansDevanagari-Bold.ttf")

    if book.latin_path:
        check("Latin font", PASS, book.latin_path)
    else:
        check("Latin font", WARN, "falling back to Pillow's default font")

    if features.check("raqm"):
        check("Raqm text shaping", PASS, "Hindi matras will render correctly")
    elif language == "hindi":
        check("Raqm text shaping", WARN,
              "missing locally, so Hindi previews will look wrong. "
              "GitHub Actions installs it, so uploads are fine. "
              "To fix locally: pip install --force-reinstall pillow")
    else:
        check("Raqm text shaping", PASS, "not needed for English")

    print()

    # --- ffmpeg ---
    try:
        import imageio_ffmpeg
        check("ffmpeg", PASS, imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as e:
        check("ffmpeg", FAIL, f"{e} - install ffmpeg or imageio-ffmpeg")

    # --- YouTube ---
    from pathlib import Path
    if os.getenv("YOUTUBE_TOKEN_JSON") or Path("config/youtube_token.json").exists():
        try:
            from src.youtube.auth import YouTubeAuth
            auth = YouTubeAuth()
            if auth.authenticate():
                response = auth.get_service().channels().list(
                    part="snippet", mine=True
                ).execute()
                items = response.get("items", [])
                name = items[0]["snippet"]["title"] if items else "unknown"
                check("YouTube auth", PASS, f"channel: {name}")
            else:
                check("YouTube auth", FAIL, "token present but not usable")
        except Exception as e:
            check("YouTube auth", FAIL, str(e))
    else:
        check("YouTube auth", FAIL,
              "no token - run: python authorize_youtube.py")

    # --- summary ---
    failures = [r for r in results if r[0] == FAIL]
    warnings = [r for r in results if r[0] == WARN]

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} blocking problem(s):")
        for _, label, detail in failures:
            print(f"  - {label}: {detail}")
        return 1

    print("All checks passed." + (f" ({len(warnings)} warning(s))" if warnings else ""))
    print("\nNext step — build one video without uploading:")
    print("  python main.py --count 1 --no-upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
