"""
Telegram Forum/Channel File Downloader using Telethon
Downloads messages and media from a Telegram forum, channel, or group.

Usage examples:
  # Basic — download all files into topic folders
  python3 tg_forum_downloader.py --api-id 12345 --api-hash abc123 --channel -1001234567890

  # Download only photos and PDFs, flat folder
  python3 tg_forum_downloader.py --api-id 12345 --api-hash abc123 --channel -1001234567890 \\
      --photos --files --flat

  # Download everything between two dates
  python3 tg_forum_downloader.py --api-id 12345 --api-hash abc123 --channel -1001234567890 \\
      --from-date 2024-01-01 --to-date 2024-06-30 --all-media

  # Download chat text only (no media)
  python3 tg_forum_downloader.py --api-id 12345 --api-hash abc123 --channel -1001234567890 \\
      --chat

  # Ignore specific topics and file types
  python3 tg_forum_downloader.py --api-id 12345 --api-hash abc123 --channel -1001234567890 \\
      --files --ignore-types mp4 zip --ignore-topics "General" "Off Topic"
"""

import asyncio
import argparse
import logging
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
    DocumentAttributeAnimated,
    DocumentAttributeSticker,
    MessageMediaDocument,
    MessageMediaPhoto,
)
from telethon.tl.functions.channels import GetForumTopicsRequest

# ─── OPTIONAL HARDCODED DEFAULTS (overridden by CLI args) ────────────────────
# Leave as None to require them on the command line
DEFAULT_API_ID   = None
DEFAULT_API_HASH = None
DEFAULT_CHANNEL  = None
DEFAULT_OUTPUT   = "./downloads"
SESSION_NAME     = "tg_forum"
MAX_FILE_SIZE_MB = 0   # 0 = no limit
# ─────────────────────────────────────────────────────────────────────────────

EXTENSION_TO_MIME = {
    "pdf":   "application/pdf",
    "epub":  "application/epub+zip",
    "zip":   "application/zip",
    "rar":   "application/x-rar-compressed",
    "7z":    "application/x-7z-compressed",
    "mp4":   "video/mp4",
    "mkv":   "video/x-matroska",
    "mov":   "video/quicktime",
    "avi":   "video/x-msvideo",
    "webm":  "video/webm",
    "mp3":   "audio/mpeg",
    "m4a":   "audio/mp4",
    "ogg":   "audio/ogg",
    "flac":  "audio/flac",
    "wav":   "audio/wav",
    "jpg":   "image/jpeg",
    "jpeg":  "image/jpeg",
    "png":   "image/png",
    "gif":   "image/gif",
    "webp":  "image/webp",
    "tiff":  "image/tiff",
    "doc":   "application/msword",
    "docx":  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls":   "application/vnd.ms-excel",
    "xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt":   "application/vnd.ms-powerpoint",
    "pptx":  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt":   "text/plain",
    "csv":   "text/csv",
    "html":  "text/html",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download messages and media from a Telegram forum, channel, or group.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
─── MEDIA TYPE FLAGS ────────────────────────────────────────────────
  If no media flags are given, ALL media types are downloaded.
  If ANY media flag is given, ONLY those types are downloaded.

─── EXAMPLES ────────────────────────────────────────────────────────

  Download everything (all media + chat text):
    python3 tg_forum_downloader.py --api-id 12345 --api-hash abc123 --channel -1001234567890

  Download only photos and files (PDFs, docs, etc):
    python3 tg_forum_downloader.py ... --photos --files

  Download only videos between two dates:
    python3 tg_forum_downloader.py ... --videos --from-date 2024-01-01 --to-date 2024-12-31

  Save chat text to a file, no media:
    python3 tg_forum_downloader.py ... --chat

  Download all media, flat folder, skip some topics:
    python3 tg_forum_downloader.py ... --all-media --flat --ignore-topics "General" "Announcements"

  Download files but skip PDFs and ZIPs:
    python3 tg_forum_downloader.py ... --files --ignore-types pdf zip
        """
    )

    # ── Credentials ──────────────────────────────────────────────────────────
    creds = parser.add_argument_group("Telegram credentials")
    creds.add_argument(
        "--api-id",
        metavar="ID",
        type=int,
        default=DEFAULT_API_ID,
        help="Telegram API ID from my.telegram.org/apps"
    )
    creds.add_argument(
        "--api-hash",
        metavar="HASH",
        default=DEFAULT_API_HASH,
        help="Telegram API hash from my.telegram.org/apps"
    )
    creds.add_argument(
        "--channel",
        metavar="ID_OR_USERNAME",
        default=DEFAULT_CHANNEL,
        help="Channel/group/forum ID (e.g. -1001234567890) or username (e.g. mygroupname)"
    )

    # ── Media types ───────────────────────────────────────────────────────────
    media = parser.add_argument_group(
        "Media types",
        "Select which types to download. If none are specified, all types are downloaded."
    )
    media.add_argument("--all-media",       action="store_true", help="Download all media types (default if no type flags given)")
    media.add_argument("--photos",          action="store_true", help="Download photos")
    media.add_argument("--videos",          action="store_true", help="Download video files")
    media.add_argument("--video-messages",  action="store_true", help="Download round video messages (video notes)")
    media.add_argument("--voice-messages",  action="store_true", help="Download voice messages")
    media.add_argument("--files",           action="store_true", help="Download documents and files (PDFs, ZIPs, etc.)")
    media.add_argument("--stickers",        action="store_true", help="Download stickers")
    media.add_argument("--gifs",            action="store_true", help="Download GIFs and animations")
    media.add_argument("--chat",            action="store_true", help="Save chat text messages to a text file")

    # ── Date range ────────────────────────────────────────────────────────────
    dates = parser.add_argument_group("Date range (optional)")
    dates.add_argument(
        "--from-date",
        metavar="YYYY-MM-DD",
        help="Only download messages on or after this date"
    )
    dates.add_argument(
        "--to-date",
        metavar="YYYY-MM-DD",
        help="Only download messages on or before this date"
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    filters = parser.add_argument_group("Filters")
    filters.add_argument(
        "--ignore-types",
        nargs="+",
        metavar="EXTENSION",
        help="File extensions to skip, e.g: --ignore-types mp4 jpg zip"
    )
    filters.add_argument(
        "--ignore-topics",
        nargs="+",
        metavar="TOPIC_NAME",
        help='Topic names to skip (case-insensitive), e.g: --ignore-topics "General" "Off Topic"'
    )

    # ── Output ────────────────────────────────────────────────────────────────
    output = parser.add_argument_group("Output")
    output.add_argument(
        "--output",
        metavar="FOLDER",
        default=DEFAULT_OUTPUT,
        help=f"Folder to save downloads (default: {DEFAULT_OUTPUT})"
    )
    output.add_argument(
        "--flat",
        action="store_true",
        help="Save all files into one folder instead of creating subfolders per topic"
    )

    args = parser.parse_args()

    # Validate required credentials
    if not args.api_id:
        parser.error("--api-id is required (or set DEFAULT_API_ID in the script)")
    if not args.api_hash:
        parser.error("--api-hash is required (or set DEFAULT_API_HASH in the script)")
    if not args.channel:
        parser.error("--channel is required (or set DEFAULT_CHANNEL in the script)")

    return args


def sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in " ._-()" else "_" for c in name).strip()


def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def get_filename(message) -> str | None:
    if not message.media or not isinstance(message.media, MessageMediaDocument):
        return None
    for attr in message.media.document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    mime = message.media.document.mime_type or "application/octet-stream"
    ext = mime.split("/")[-1]
    return f"file_{message.id}.{ext}"


def classify_message(message) -> str | None:
    """
    Returns the media category of a message:
    photo, video, video_message, voice, sticker, gif, file
    Returns None if no downloadable media.
    """
    if isinstance(message.media, MessageMediaPhoto):
        return "photo"

    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        attrs = doc.attributes

        for attr in attrs:
            if isinstance(attr, DocumentAttributeSticker):
                return "sticker"

        for attr in attrs:
            if isinstance(attr, DocumentAttributeAnimated):
                return "gif"

        for attr in attrs:
            if isinstance(attr, DocumentAttributeVideo):
                if attr.round_message:
                    return "video_message"
                return "video"

        for attr in attrs:
            if isinstance(attr, DocumentAttributeAudio):
                if attr.voice:
                    return "voice"

        return "file"

    return None


def should_download(category: str, args, ignored_mimes: set, message) -> bool:
    """Decide whether to download based on category and active filters."""
    if category is None:
        return False

    # Check MIME ignore list (only applies to document-based media)
    if category == "file" and isinstance(message.media, MessageMediaDocument):
        if message.media.document.mime_type in ignored_mimes:
            return False

    # Check file size limit
    if isinstance(message.media, MessageMediaDocument):
        if MAX_FILE_SIZE_MB > 0 and message.media.document.size > MAX_FILE_SIZE_MB * 1024 * 1024:
            log.info(f"  Skipping oversized file (msg {message.id})")
            return False

    # If no specific media flags were set, download everything
    any_media_flag = any([
        args.all_media, args.photos, args.videos, args.video_messages,
        args.voice_messages, args.files, args.stickers, args.gifs
    ])
    if not any_media_flag:
        return True

    if args.all_media:
        return True

    return (
        (args.photos         and category == "photo")         or
        (args.videos         and category == "video")         or
        (args.video_messages and category == "video_message") or
        (args.voice_messages and category == "voice")         or
        (args.files          and category == "file")          or
        (args.stickers       and category == "sticker")       or
        (args.gifs           and category == "gif")
    )


def in_date_range(message, from_date, to_date) -> bool:
    if not message.date:
        return True
    msg_date = message.date.replace(tzinfo=timezone.utc)
    if from_date and msg_date < from_date:
        return False
    if to_date and msg_date > to_date:
        return False
    return True


def load_downloaded_ids(base_dir: Path) -> set:
    id_file = base_dir / "downloaded_ids.json"
    if id_file.exists():
        with open(id_file) as f:
            return set(json.load(f))
    return set()


def save_downloaded_ids(base_dir: Path, ids: set):
    id_file = base_dir / "downloaded_ids.json"
    with open(id_file, "w") as f:
        json.dump(list(ids), f)


async def get_all_topics(client, forum):
    topics = []
    offset_id = 0
    while True:
        result = await client(GetForumTopicsRequest(
            channel=forum, q="",
            offset_date=0, offset_id=offset_id,
            offset_topic=0, limit=100,
        ))
        if not result.topics:
            break
        topics.extend(result.topics)
        if len(result.topics) < 100:
            break
        offset_id = result.topics[-1].id
    return topics


async def process_messages(client, messages_iter, save_dir: Path, chat_log,
                           args, ignored_mimes: set,
                           downloaded_ids: set, base_dir: Path,
                           from_date, to_date):
    downloaded = skipped = text_saved = 0

    async for message in messages_iter:
        # Date filter
        if not in_date_range(message, from_date, to_date):
            continue

        # Save chat text
        if args.chat and message.text:
            ts = message.date.strftime("%Y-%m-%d %H:%M:%S") if message.date else "unknown"
            sender = getattr(message.sender, "username", None) or str(getattr(message.sender_id, "user_id", message.sender_id) if message.sender_id else "unknown")
            chat_log.write(f"[{ts}] {sender}: {message.text}\n")
            text_saved += 1

        # Classify media
        category = classify_message(message)
        if not should_download(category, args, ignored_mimes, message):
            continue

        # Skip already downloaded
        if message.id in downloaded_ids:
            log.info(f"  ✅ Already downloaded (id={message.id}), skipping")
            skipped += 1
            continue

        # Determine filename
        if category == "photo":
            filename = f"photo_{message.id}.jpg"
        else:
            filename = get_filename(message) or f"file_{message.id}"

        filepath = save_dir / sanitize(filename)

        # Check existing file size for documents
        if filepath.exists() and category != "photo":
            expected = message.media.document.size
            if filepath.stat().st_size == expected:
                log.info(f"  ✅ Exists with correct size, skipping: {filename}")
                downloaded_ids.add(message.id)
                skipped += 1
                continue

        size_str = ""
        if category != "photo" and isinstance(message.media, MessageMediaDocument):
            size_str = f" ({message.media.document.size // 1024}KB)"

        log.info(f"  ⬇️  [{category}] {filename}{size_str}")

        try:
            await client.download_media(message, file=str(filepath))
            downloaded_ids.add(message.id)
            save_downloaded_ids(base_dir, downloaded_ids)
            log.info(f"  ✔️  Saved: {filepath}")
            downloaded += 1
        except Exception as e:
            log.error(f"  ❌ Failed: {filename}: {e}")

    return downloaded, skipped, text_saved


async def main():
    args = parse_args()

    # Build ignored MIME set
    ignored_mimes = set()
    if args.ignore_types:
        for ext in args.ignore_types:
            ext = ext.lower().lstrip(".")
            mime = EXTENSION_TO_MIME.get(ext)
            if mime:
                ignored_mimes.add(mime)
                log.info(f"Ignoring file type: .{ext} ({mime})")
            else:
                log.warning(f"Unknown extension '{ext}', no ignore rule added")

    ignored_topics = set()
    if args.ignore_topics:
        ignored_topics = {t.lower() for t in args.ignore_topics}
        log.info(f"Ignoring topics: {', '.join(args.ignore_topics)}")

    from_date = parse_date(args.from_date)
    to_date   = parse_date(args.to_date)
    if from_date:
        log.info(f"From date: {args.from_date}")
    if to_date:
        log.info(f"To date:   {args.to_date}")

    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    log.info(f"📂 Output: {output_path.resolve()}")
    log.info(f"📁 Mode:   {'Flat' if args.flat else 'By topic'}")

    # Resolve channel ID or username
    channel_input = args.channel
    try:
        channel_input = int(args.channel)
    except ValueError:
        pass  # keep as string username

    async with TelegramClient(SESSION_NAME, args.api_id, args.api_hash) as client:
        log.info("🔌 Connected to Telegram")

        try:
            forum = await client.get_entity(channel_input)
            log.info(f"📣 Chat: {getattr(forum, 'title', forum)}")
        except Exception as e:
            log.error(f"❌ Could not find channel/forum: {e}")
            return

        downloaded_ids = load_downloaded_ids(output_path)
        log.info(f"📝 {len(downloaded_ids)} previously downloaded IDs loaded")

        total_dl = total_sk = total_txt = 0

        # Open chat log file if --chat requested
        chat_log_path = output_path / "chat.txt"
        chat_log_file = open(chat_log_path, "a", encoding="utf-8") if args.chat else open(os.devnull, "w")

        with chat_log_file as chat_log:
            # Try forum topics
            try:
                topics = await get_all_topics(client, forum)
                log.info(f"Found {len(topics)} topic(s)")
            except Exception as e:
                log.warning(f"Could not fetch topics ({e}), falling back to flat download")
                topics = None

            if topics:
                for topic in topics:
                    if topic.title.lower() in ignored_topics:
                        log.info(f"⏭️  Skipping topic: {topic.title}")
                        continue

                    log.info(f"\n📁 Topic: {topic.title} (id={topic.id})")

                    save_dir = output_path if args.flat else output_path / f"{topic.id}_{sanitize(topic.title)}"
                    save_dir.mkdir(parents=True, exist_ok=True)

                    msgs = client.iter_messages(forum, reply_to=topic.id, limit=None)
                    dl, sk, txt = await process_messages(
                        client, msgs, save_dir, chat_log,
                        args, ignored_mimes, downloaded_ids, output_path,
                        from_date, to_date
                    )
                    total_dl += dl; total_sk += sk; total_txt += txt
                    log.info(f"  → Downloaded: {dl}, Skipped: {sk}, Text messages: {txt}")

            else:
                log.info("Downloading from main group/channel...")
                msgs = client.iter_messages(forum, limit=None)
                total_dl, total_sk, total_txt = await process_messages(
                    client, msgs, output_path, chat_log,
                    args, ignored_mimes, downloaded_ids, output_path,
                    from_date, to_date
                )

        log.info(f"\n🎉 Done!")
        log.info(f"   Downloaded:     {total_dl}")
        log.info(f"   Skipped:        {total_sk}")
        if args.chat:
            log.info(f"   Text messages:  {total_txt} → {chat_log_path}")
        log.info(f"   Saved to:       {output_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
