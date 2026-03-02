"""
Telegram Forum File Downloader using Telethon
Downloads files from all topics in a private Telegram forum/supergroup.
Supports resume, file type filtering, and organizes by topic.
"""

import os
import asyncio
import logging
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageMediaDocument,
)
from telethon.tl.functions.channels import GetForumTopicsRequest

# ─── CONFIGURATION ───────────────────────────────────────────────────────────

API_ID =            # Replace with your api_id from my.telegram.org
API_HASH = ""  # Replace with your api_hash from my.telegram.org
SESSION_NAME = "tg_forum"   # Session file name (saved locally)

# The forum group: use numeric ID like -1001234567890 or username like "mygroup"
FORUM_ID =

# Output directory for downloaded files
OUTPUT_DIR = "./"

# File types to download (MIME types). Leave empty [] to download ALL file types.
ALLOWED_MIME_TYPES = [
    "application/pdf",
    # "image/jpeg",
    # "image/png",
    # "video/mp4",
    # "application/zip",
    # "application/epub+zip",
]

# Max file size in MB (0 = no limit)
MAX_FILE_SIZE_MB = 0

# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def sanitize(name: str) -> str:
    """Remove characters unsafe for folder/file names."""
    return "".join(c if c.isalnum() or c in " ._-()" else "_" for c in name).strip()


def get_filename(message) -> str | None:
    """Extract original filename from a document message."""
    if not message.media or not isinstance(message.media, MessageMediaDocument):
        return None
    for attr in message.media.document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    # Fallback: use message ID + mime type extension
    mime = message.media.document.mime_type or "application/octet-stream"
    ext = mime.split("/")[-1]
    return f"file_{message.id}.{ext}"


def is_allowed(message) -> bool:
    """Check if message has a file we want to download."""
    if not message.media or not isinstance(message.media, MessageMediaDocument):
        return False
    doc = message.media.document
    if ALLOWED_MIME_TYPES and doc.mime_type not in ALLOWED_MIME_TYPES:
        return False
    if MAX_FILE_SIZE_MB > 0 and doc.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        log.info(f"  Skipping large file ({doc.size // (1024*1024)}MB): msg {message.id}")
        return False
    return True


async def get_all_topics(client, forum):
    """Fetch all topics from a forum supergroup."""
    topics = []
    offset_id = 0
    while True:
        result = await client(GetForumTopicsRequest(
            channel=forum,
            q="",
            offset_date=0,
            offset_id=offset_id,
            offset_topic=0,
            limit=100,
        ))
        if not result.topics:
            break
        topics.extend(result.topics)
        if len(result.topics) < 100:
            break
        offset_id = result.topics[-1].id
    return topics


async def download_topic(client, forum, topic, base_dir: Path):
    """Download all matching files from a single topic."""
    topic_name = sanitize(topic.title)
    topic_dir = base_dir / f"{topic.id}_{topic_name}"
    topic_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"📁 Topic: {topic.title} (id={topic.id})")

    downloaded = 0
    skipped = 0

    async for message in client.iter_messages(forum, reply_to=topic.id, limit=None):
        if not is_allowed(message):
            continue

        filename = get_filename(message)
        if not filename:
            continue

        filepath = topic_dir / sanitize(filename)

        # Resume: skip if file already fully downloaded
        if filepath.exists():
            expected_size = message.media.document.size
            if filepath.stat().st_size == expected_size:
                log.info(f"  ✅ Already exists, skipping: {filename}")
                skipped += 1
                continue
            else:
                log.info(f"  ⚠️  Incomplete file, re-downloading: {filename}")

        log.info(f"  ⬇️  Downloading: {filename} ({message.media.document.size // 1024}KB)")

        try:
            await client.download_media(message, file=str(filepath))
            log.info(f"  ✔️  Saved: {filepath}")
            downloaded += 1
        except Exception as e:
            log.error(f"  ❌ Failed to download {filename}: {e}")

    log.info(f"  → Downloaded: {downloaded}, Skipped (already exist): {skipped}\n")
    return downloaded


async def main():
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        log.info("🔌 Connected to Telegram")

        # Resolve the forum entity
        try:
            forum = await client.get_entity(FORUM_ID)
            log.info(f"📣 Forum: {forum.title}")
        except Exception as e:
            log.error(f"❌ Could not find forum: {e}")
            return

        # Get all topics
        log.info("📋 Fetching topics...")
        try:
            topics = await get_all_topics(client, forum)
            log.info(f"Found {len(topics)} topic(s)")
        except Exception as e:
            log.error(f"❌ Could not fetch topics (is this a forum/supergroup?): {e}")
            log.info("Falling back to downloading from main chat (no topics)...")
            topics = None

        total = 0

        if topics:
            for topic in topics:
                count = await download_topic(client, forum, topic, output_path)
                total += count
        else:
            # Fallback: no topics, just download from the group directly
            log.info("Downloading from main group (no topic structure)...")
            async for message in client.iter_messages(forum, limit=None):
                if not is_allowed(message):
                    continue
                filename = get_filename(message)
                if not filename:
                    continue
                filepath = output_path / sanitize(filename)
                if filepath.exists() and filepath.stat().st_size == message.media.document.size:
                    log.info(f"  ✅ Already exists: {filename}")
                    continue
                log.info(f"  ⬇️  Downloading: {filename}")
                await client.download_media(message, file=str(filepath))
                total += 1

        log.info(f"\n🎉 Done! Total files downloaded: {total}")
        log.info(f"📂 Saved to: {output_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
