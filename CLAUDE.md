# slack-tools

Slack CLI for AI agent use and automation.
Run `slack-tools --help` or `slack-tools <command> --help` for usage details.

## Key Info

- All commands output JSON
- Auth: `.env` file (SLACK_USER_TOKEN, SLACK_BOT_TOKEN)
- `search` requires User Token (xoxp-), other commands use Bot Token (xoxb-)

## Commands

| Command | Description | Token |
|---------|-------------|-------|
| `slack-tools search "검색어"` | 메시지 검색 | User |
| `slack-tools history <channel> --since 2h` | 채널 최근 메시지 | Bot |
| `slack-tools thread <channel> <thread_ts>` | 스레드 전체 조회 | Bot |
| `slack-tools post <channel> "메시지"` | 메시지 전송 | Bot |
| `slack-tools reply <channel> <thread_ts> "메시지"` | 스레드 답장 | Bot |
| `slack-tools users [-q "이름"]` | 사용자 목록/검색 | Bot |
| `slack-tools channels [-q "이름"] [-p]` | 채널 목록 (--private 포함 가능) | Bot |
| `slack-tools usergroups [-m]` | 유저그룹 목록 (--members 포함 가능) | Bot |

## Search Modifiers

Slack 검색 문법 사용 가능:
- `in:#channel-name` — 특정 채널에서 검색
- `from:@username` — 특정 사용자 메시지
- `before:2026-01-01` / `after:2026-01-01` — 날짜 범위
- `has:link` / `has:emoji` — 필터
