"""
Intent Detector Hook
- agent:end       → detect incomplete conversation via LLM, save to queue + MEMORY.md
- agent:start     → if user returns after idle 1+ hour with pending intent, send Telegram follow-up
- gateway:startup → start background inactivity watcher (checks every 30 min)
"""

import asyncio
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

IDLE_THRESHOLD_HOURS = 1.0  # consider user idle if no activity for 1+ hour
CHECK_INTERVAL_SECONDS = 30 * 60  # watcher checks every 30 minutes
QUEUE_FILE = Path.home() / ".hermes" / "intent_queue.json"
LAST_SEEN_FILE = Path.home() / ".hermes" / "intent_last_seen.json"
MEMORY_FILE = Path.home() / ".hermes" / "memories" / "MEMORY.md"
ENTRY_DELIMITER = "\n§\n"


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_queue(queue: list) -> None:
    # Drop resolved entries older than 7 days to keep the file clean
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    queue = [
        item for item in queue
        if not item.get("resolved", False) or item.get("detected_at", "") > cutoff
    ]
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def get_pending_intents(user_id: str) -> list:
    """Return unresolved intents for a specific user."""
    return [
        item for item in load_queue()
        if item.get("user_id") == user_id and not item.get("resolved", False)
    ]


def mark_resolved(user_id: str) -> None:
    """Mark all pending intents for a user as resolved."""
    queue = load_queue()
    for item in queue:
        if item.get("user_id") == user_id:
            item["resolved"] = True
    save_queue(queue)


# ---------------------------------------------------------------------------
# last_seen tracker
# ---------------------------------------------------------------------------

def update_last_seen(user_id: str) -> None:
    data = {}
    if LAST_SEEN_FILE.exists():
        try:
            data = json.loads(LAST_SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[user_id] = datetime.now().isoformat()
    LAST_SEEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def format_time_ago(iso_timestamp: str) -> str:
    """Convert ISO timestamp to natural Indonesian: '5 menit lalu', '2 jam lalu', 'kemarin'."""
    try:
        past = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now() - past
        seconds = int(delta.total_seconds())

        if seconds < 60:
            return "barusan"
        if seconds < 3600:
            return f"{seconds // 60} menit lalu"
        if seconds < 86400:
            return f"{seconds // 3600} jam lalu"
        if seconds < 172800:
            return "kemarin"
        if seconds < 604800:
            return f"{seconds // 86400} hari lalu"
        return past.strftime("%d %B %Y")
    except Exception:
        return "sebelumnya"


def get_idle_hours(user_id: str) -> float:
    """Return how many hours since user was last active. 999 if unknown."""
    if not LAST_SEEN_FILE.exists():
        return 999.0
    try:
        data = json.loads(LAST_SEEN_FILE.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(data.get(user_id, ""))
        return (datetime.now() - last).total_seconds() / 3600
    except Exception:
        return 999.0


# ---------------------------------------------------------------------------
# MEMORY.md writer — agent reads this naturally at next session init
# ---------------------------------------------------------------------------

def write_to_memory(reason: str, suggestion: str) -> None:
    """Replace the [Pending follow-up] entry in MEMORY.md (only one at a time)."""
    entry = (
        f"[Catatan pribadi — belum selesai]\n"
        f"Di percakapan sebelumnya, {reason}. "
        f"Saya belum sempat menindaklanjuti ini. "
        f"Saya perlu menyinggung ini secara natural di awal percakapan ini sebelum terlalu jauh. "
        f"Setelah saya tanyakan, saya akan hapus catatan ini dari memory."
    )
    if suggestion:
        entry += f"\nRencana kalimat saya: \"{suggestion}\""

    # Remove ALL existing pending entries first, then add the new one
    current = MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.exists() else ""
    entries = [e for e in current.split(ENTRY_DELIMITER) if "[Catatan pribadi" not in e and e.strip()]
    entries.append(entry)
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(ENTRY_DELIMITER.join(entries), encoding="utf-8")
    print(f"[intent-detector] Written to MEMORY.md: {reason[:60]}", flush=True)


def clear_pending_from_memory() -> None:
    """Remove pending entries from MEMORY.md only."""
    if not MEMORY_FILE.exists():
        return
    current = MEMORY_FILE.read_text(encoding="utf-8")
    entries = [e for e in current.split(ENTRY_DELIMITER) if "[Catatan pribadi" not in e and e.strip()]
    MEMORY_FILE.write_text(ENTRY_DELIMITER.join(entries), encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM intent analysis
# ---------------------------------------------------------------------------

async def analyze_intent_with_llm(message: str, response: str) -> dict:
    """Ask a small LLM: does this conversation need a follow-up?"""
    try:
        import httpx

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return {"needs_followup": False, "reason": "no api key", "suggestion": ""}

        prompt = f"""Kamu adalah asisten yang menganalisis apakah sebuah percakapan sudah TUNTAS atau belum.

Pesan user: "{message}"
Jawaban agent: "{response}"

Pertanyaan kunci: Apakah MASALAH ATAU TUJUAN USER sudah benar-benar terselesaikan?

Percakapan BELUM TUNTAS jika:
- User mengeluh tentang masalah nyata (kesehatan, akademik, pekerjaan, emosional) yang BELUM benar-benar terselesaikan oleh jawaban agent
- Agent kasih kerangka/opsi tapi minta info lebih lanjut dari user untuk menyelesaikan masalah aslinya
- User menyebut deadline/tugas spesifik dan masih dalam tahap awal (belum jelas akan diselesaikan)
- User menyatakan kebingungan/kebutuhan bantuan untuk problem yang belum tuntas dijawab

Percakapan SUDAH TUNTAS jika:
- Basa-basi atau salam (halo, hai, terima kasih, dll)
- User minta rekomendasi/info dan agent kasih jawaban lengkap, lalu menutup dengan offer opsional ("kalau mau saya bisa lebih spesifik")
- Pertanyaan faktual sudah dijawab tuntas (berapa 2+2, apa itu X, kapan Y)
- Perintah sudah dieksekusi

Pembedaan PENTING:
- "rekomendasikan lagu" → agent kasih daftar lagu → TUNTAS (problem user adalah ingin daftar, sudah dapat)
- "saya bingung belum ada topik thesis" → agent kasih kerangka tapi minta jurusan/minat → BELUM TUNTAS (problem user adalah belum punya topik, masih belum selesai)
- "obat untuk pusing" + user bilang "saya pusing sekarang" → BELUM TUNTAS (kondisi user masih bermasalah)
- "obat untuk pusing" tanya teori saja → TUNTAS (sudah dijawab faktual)

Jawab JSON:
{{
  "is_complete": true/false,
  "reason": "alasan singkat kenapa tuntas atau belum",
  "suggestion": "kalimat natural follow-up jika belum tuntas (kosong jika sudah tuntas)"
}}

Jawab JSON saja."""

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.1,
                },
            )
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)

    except Exception as e:
        print(f"[intent-detector] LLM analysis failed: {e}", flush=True)
        return {"needs_followup": False, "reason": str(e), "suggestion": ""}


# ---------------------------------------------------------------------------
# Telegram sender
# ---------------------------------------------------------------------------

async def send_telegram_message(chat_id: str, text: str, bot_token: str) -> None:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception as e:
        print(f"[intent-detector] Telegram send failed: {e}", flush=True)


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

async def handle(event_type: str, context: dict) -> None:
    # gateway:startup is system-level — no platform/user_id
    if event_type == "gateway:startup":
        asyncio.create_task(_inactivity_watcher())
        print("[intent-detector] Inactivity watcher started", flush=True)
        return

    platform = context.get("platform", "")
    user_id = context.get("user_id", "")

    if platform != "telegram" or not user_id:
        return

    # ------------------------------------------------------------------
    # agent:end — detect intent and save
    # ------------------------------------------------------------------
    if event_type == "agent:end":
        message = context.get("message", "")
        response = context.get("response", "")

        if not message:
            return

        update_last_seen(user_id)

        # Skip detection if user already has unresolved intent (avoid duplicates)
        if get_pending_intents(user_id):
            print(f"[intent-detector] User already has pending intent, skipping detection", flush=True)
            return

        intent = await analyze_intent_with_llm(message, response)

        if intent.get("is_complete", True):
            print(f"[intent-detector] Conversation complete, no follow-up: {intent.get('reason', '')}", flush=True)
            return

        print(f"[intent-detector] Intent saved: {intent.get('reason', '')}", flush=True)

        queue = load_queue()
        queue.append({
            "detected_at": datetime.now().isoformat(),
            "user_id": user_id,
            "platform": platform,
            "message": message[:300],
            "reason": intent.get("reason", ""),
            "suggestion": intent.get("suggestion", ""),
            "resolved": False,
        })
        save_queue(queue)

        # Write to MEMORY.md so agent reads it naturally at next session init
        write_to_memory(intent.get("reason", ""), intent.get("suggestion", ""))

    # ------------------------------------------------------------------
    # agent:start — user just sent a message. If they were idle 1+ hour
    # and have pending intents, send follow-up BEFORE agent replies.
    # ------------------------------------------------------------------
    elif event_type == "agent:start":
        pending = get_pending_intents(user_id)
        if not pending:
            return

        idle_hours = get_idle_hours(user_id)
        if idle_hours < IDLE_THRESHOLD_HOURS:
            return

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            return

        latest = pending[-1]
        suggestion = latest.get("suggestion", "")
        time_ago = format_time_ago(latest.get("detected_at", ""))
        followup_text = (
            f"Btw Figo, {time_ago} kamu sempat bahas sesuatu yang belum selesai — "
            f"{suggestion if suggestion else latest.get('message', '')[:150]}"
        )

        print(f"[intent-detector] User returned after {idle_hours:.1f}h idle — sending follow-up", flush=True)
        await send_telegram_message(user_id, followup_text, bot_token)
        mark_resolved(user_id)
        clear_pending_from_memory()

    # ------------------------------------------------------------------
    # gateway:startup — start background inactivity watcher
    # ------------------------------------------------------------------
    elif event_type == "gateway:startup":
        asyncio.create_task(_inactivity_watcher())
        print("[intent-detector] Inactivity watcher started", flush=True)


async def _inactivity_watcher() -> None:
    """Background loop: every 30 min, check for idle users with pending intents."""
    await asyncio.sleep(60)  # wait 1 min after startup before first check
    while True:
        try:
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if not bot_token:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                continue

            # Load all unique user IDs from queue that have unresolved intents
            queue = load_queue()
            pending_users = {
                item["user_id"]
                for item in queue
                if not item.get("resolved", False) and item.get("platform") == "telegram"
            }

            for user_id in pending_users:
                idle_hours = get_idle_hours(user_id)
                if idle_hours < IDLE_THRESHOLD_HOURS:
                    continue

                pending = get_pending_intents(user_id)
                if not pending:
                    continue

                latest = pending[-1]
                suggestion = latest.get("suggestion", "")
                time_ago = format_time_ago(latest.get("detected_at", ""))
                reminder_text = (
                    f"Hei Figo, {time_ago} kamu sempat bahas: "
                    f"\"{latest.get('message', '')[:120]}\"\n\n"
                    f"{suggestion if suggestion else 'Ada update atau perlu dilanjutkan?'}"
                )

                print(
                    f"[intent-detector] Inactivity reminder sent to {user_id} "
                    f"(idle {idle_hours:.1f}h)",
                    flush=True,
                )
                await send_telegram_message(user_id, reminder_text, bot_token)
                mark_resolved(user_id)

        except Exception as e:
            print(f"[intent-detector] Watcher error: {e}", flush=True)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
