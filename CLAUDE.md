# slack-tools

Slack CLI for AI agent use and automation.
Run `slack-tools --help` or `slack-tools <command> --help` for usage details.

## Key Info

- All commands output JSON
- Auth: `.env` file (SLACK_USER_TOKEN, SLACK_BOT_TOKEN)
- `search` requires User Token (xoxp-), other commands use Bot Token (xoxb-)

## Search Modifiers

Slack 검색 문법 사용 가능:
- `in:#channel-name` — 특정 채널에서 검색
- `from:@username` — 특정 사용자 메시지
- `before:2026-01-01` / `after:2026-01-01` — 날짜 범위
- `has:link` / `has:emoji` — 필터
