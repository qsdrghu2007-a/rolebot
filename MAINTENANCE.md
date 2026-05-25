# Telegram Roleplay Bot — Maintenance Guide

## Architecture Overview

```
main.py                        # Entry point: config loading, dependency check, bot launch
telegram_bot.py                # Core: command handling, message flow, mood system, callback dispatch
llm_client.py                  # LLM API client (OpenAI-compatible, supports arbitrary base_url)
prompt_engine.py               # Prompt engine (KV cache optimization, mood injection)
memory_db.py                   # SQLite database (6 tables + mood/erotic/compact CRUD)
ai_memory_manager.py           # AI memory judge + ArousalJudge
world_book.py                  # World book keyword matcher
setup.py                       # First-time setup wizard (interactive, bilingual)
config.yaml                    # Runtime config (llm section: api_key / base_url / model)
config.example.yaml            # Config template
digital_person/
  persona_final-d.md           # Character persona (template, user fills in)
  world_book.json              # World book example entries
```

> **Note**: This is a generic template with no hardcoded character content. Users customize their bot via `persona_final-d.md` and `config.yaml`.

## Data Flow

```
User message
  → handle_text_message()
    → reply_to_message detected? → _handle_edit (edit mode)
    → _get_mood_state()          → lazy time decay
    → build_messages(mood)       → messages[0]=persona, [1..N-1]=history, [N]=WB+mood+msg
    → generate_response()        → sync LLM call
    → _release_missing_if_expressed() / _track_response()
    → add_message(user + assistant) to DB
    → create_task → _process_memory_async (memory + mood delta)
    → create_task → _process_arousal_async (arousal state machine)
```

## KV Cache Structure

```
messages[0]      persona + long-term memories    ← fixed → cache hit
messages[1..N-1] conversation history            ← stable old messages → cache hit
messages[N]      WB + mood + focus reminder + user message ← changes every turn
```

Actual hit rate ~**96%** (98 out of 102 messages hit with max_history=100).

## All Commands

| Command | Handler | Description |
|------|---------|------|
| `/start` | start_command | Welcome message |
| `/help` | help_command | Help text |
| `/mood` | mood_command | 5D mood with progress bars |
| `/continue` | continue_command | Bot continues generating on its own |
| `/regenerate` | regenerate_command | Regenerate last reply, discard old |
| `/suggest` | suggest_command | Parallel 3-way LLM generation of candidate user replies |
| `/clear` | clear_command | Clear chat history (prompts for compact first) |
| `/clear_memories` | clear_memories_command | Clear all long-term memories (requires confirmation) |
| `/list_memories` | list_memories_command | List all long-term memories |
| `/delete_memory <N>` | delete_memory_command | Delete a memory by number (no arg = paginated buttons) |
| `/thinking` | thinking_command | Thinking mode high/max/off (button UI) |
| `/language` | language_command | Switch language (中文/English) |
| `/compact` | compact_command | Summarize chat as diary entry |
| `/compact list` | compact_command(args) | Browse diary history |
| `/status` | status_command | 4-tab dashboard (overview/data/history/mood) |

## Database Schema

### conversations (chat history)
| Column | Type | Description |
|----|------|------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT | Telegram user ID |
| role | TEXT | user / assistant |
| content | TEXT | Message content |
| timestamp | DATETIME | Timestamp |
| is_important | INTEGER | Whether marked as important |
| telegram_msg_id | INTEGER | Corresponding Telegram message ID (for edit feature) |
| erotic_active | INTEGER | Whether in arousal mode after this judgment (user rows only) |
| erotic_enter_count | INTEGER | Consecutive true count after this judgment (user rows only) |
| erotic_exit_count | INTEGER | Consecutive false count after this judgment (user rows only) |

### user_memories (long-term memories)
| id | user_id | memory_type | content | importance | created_at | last_accessed |
|----|---------|-------------|---------|------------|------------|---------------|

### user_info (user info)
| user_id | nickname | first_seen | last_seen | total_messages | settings(JSON) |
|---------|----------|------------|-----------|----------------|----------------|

settings JSON structure:
```json
{
  "mood": {"happiness":7, "missing":3, "energy":7, "anger":1, "arousal":3},
  "mood_updated": "2026-05-25 14:30",
  "erotic": {"active": false, "count_enter": 0, "count_exit": 0},
  "last_clear": "2026-05-25 14:00"
}
```

### compact_records (diary summaries)
| id | user_id | title | content | created_at |
|----|---------|-------|---------|------------|

## Mood System (5 dimensions, 0-10)

### Lazy time decay (computed on message receipt)
| Dimension | Default | Decay formula | Description |
|------|------|---------|------|
| happiness | 7 | -0.1/h | Slowly drops when not chatting |
| missing | 3 | +0.15/h | Grows the longer you're away (only dimension that increases over time) |
| energy | 7 | Late night -1 / Morning +0.5 / Otherwise -0.1/h | Simulates daily rhythm |
| anger | 1 | -0.3/h | Fades on its own |
| arousal | 3 | +2.0/h | Maxes out in ~5h |

### Two channels that reduce missing
1. **AI judgment**: user returns / happy chat → missing -1 to -2
2. **Expression release**: bot reply contains expressive keywords → missing -0.5

### Injection location
`prompt_engine.py: _build_user_content()` → end of messages[N]
Format: `【你的内在状态】你现在{feeling description}（这只是内心感受，不要直接说出来，用来影响说话的语气即可）`

> **Generic edition note**: mood descriptions use neutral phrasing (no role-specific pet names).

## Arousal State Machine

### ArousalJudge (independent API call)
- Model: configured via `llm.model`, temp=0, max_tokens=10, thinking=disabled
- Judges true/false only: **explicit sexual acts / dirty talk / erotic roleplay** → true
- Hugging, cuddling, flirting, post-coital comfort → false

### State machine
```
Entry: 2 consecutive true → active=true, arousal=10
Exit:  3 consecutive false → active=false, arousal=0
Reset: any true while active → count_exit=0
```

### Arousal trigger rules per command

| Path | Triggers arousal? | Reason |
|------|:---:|------|
| Normal chat `_process_message` | ✓ | New user message, must judge |
| `/continue` | ✗ | No new user message, bot continues solo |
| `/regenerate` | ✗ | Bot regenerates its own reply; user message unchanged |
| `/suggest` selection | ✓ | Selected text is stored as user utterance in DB |
| `_handle_edit` editing own msg | ✓ | Edited content is new user input |
| `_handle_edit` editing bot msg | ✗ | Edit target is not a user message |

### Arousal snapshot system

After each user message is judged, the state machine's current state (`active`, `enter_count`, `exit_count`) is written to the `erotic_*` columns of the `conversations` table. Bot message rows are never written to.

**Purpose of snapshots**: restoring the state machine after message edits.

**Edit flow (`_handle_edit`)**:

```
1. If editing own message → reset_arousal_snapshot(db_id)   // Invalidate old judgment
2. edit_message_content(db_id, reply_text)                   // Overwrite content
3. delete_messages_from_id(db_id + 1)                        // Delete later messages + their snapshots
4. prev = get_last_arousal_snapshot_before(user_id, db_id)   // Find nearest snapshot before edit point
5. save_erotic_state(prev)                                    // Roll back state machine to edit point
6. If regenerate triggers AND editing own message:
   → _process_arousal_async(new_content, user_msg_db_id)     // Judge new content + write snapshot
```

**Snapshot methods** (`memory_db.py`):

| Method | Purpose |
|------|------|
| `set_arousal_snapshot(conv_id, active, enter, exit)` | Write the three columns |
| `get_last_arousal_snapshot_before(user_id, before_id)` | Find nearest user-message snapshot before a given ID |
| `reset_arousal_snapshot(conv_id)` | Set to NULL (old judgment invalidated by edit) |

**Dual-counter semantics**:

| erotic_active | enter_count | exit_count |
|:---:|:---:|:---:|
| 0 (not in mode) | Active counter | Fixed at 0 |
| 1 (in mode) | Fixed at 0 | Active counter |

Never modify both counters simultaneously. Which counter is active is determined by `erotic_active`. Both are zeroed on state transition.

## Callback Data Formats

| Prefix | Format | Purpose |
|------|------|------|
| `think:` | high/max/off | Thinking mode toggle |
| `delmem:` | `id:page` | Delete memory |
| `delmem_page:` | `page` | Memory pagination |
| `suggest:` | 0/1/2/cancel | Select candidate reply |
| `compact_view:` | `id` | View diary detail |
| `compact_list` | — | Return to diary list |
| `compact_page:` | `page` | Diary pagination |
| `compact_delete:` | `id` | Delete diary entry |
| `clear:` | compact/direct/cancel | Clear decision |
| `status:` | overview/data/history/mood | Status tab switch |
| `noop` | — | Current-tab button (no operation) |

## Design Decisions

### Why SQLite instead of MySQL/PostgreSQL
- Zero configuration, zero dependent services
- Sufficient for single-user / small-scale use
- Database file can be backed up directly

### Why LLM calls are synchronous
- `asyncio.get_event_loop().run_in_executor()` wraps synchronous `requests` calls
- Better compatibility; no extra async HTTP library required
- Streaming responses showed no meaningful UX improvement over fast sync calls

### Why thinking mode defaults to on
- Models like DeepSeek produce noticeably better responses with thinking enabled
- Users can toggle off with `/thinking off` for speed

### Bilingual support
- `/language` command switches the user interface between Chinese and English
- Language preference is stored in `user_info.settings.language`, effective immediately
- The language chosen during `setup.py` is automatically written to `config.yaml` as `bot.language` and used as the default for new users
- Translation dictionaries are in the `T` dict at the top of `telegram_bot.py`, covering ~80 keys across all user-facing messages

## Known Pitfalls

1. **`delete_messages_from_id` was once lost** — The edit feature depends on this method. Ensure it exists in memory_db.py (near line 657).
2. **Timestamp fallback** — Both `clear_command` and `_do_compact` use `get_recent_conversation` as a fallback in case timestamp format mismatches cause empty results.
3. **Mood injection reform** — Changed from `【当前心情】` to `【你的内在状态】` directive format to prevent the LLM from acting directly on mood descriptions.
4. **World book format compatibility** — `world_book.py` supports both `keys` and `keywords` fields. The JSON can be a plain array or an `{"entries": [...]}` object.
5. **First-time run** — Run `python setup.py` for guided configuration. Both `config.yaml` and `persona_final-d.md` are templates that must be filled in before use.
6. **Arousal snapshots are only on user rows** — `set_arousal_snapshot` is only called for `role='user'` conversation rows. Bot rows have NULL for all three erotic_* columns.
7. **Editing bot messages still restores the state machine** — Even when the edit target is not a user message, `_handle_edit` still rolls back to the nearest snapshot. This is necessary because deleting subsequent messages may have removed intermediate user-message snapshots.
