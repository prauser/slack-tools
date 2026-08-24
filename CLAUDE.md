# slack-tools

Slack CLI for AI agent use and automation.
Run `slack-tools --help` or `slack-tools <command> --help` for usage details.

## Key Info

- All commands output JSON
- Auth: `.env` file (SLACK_USER_TOKEN, SLACK_BOT_TOKEN)
- `search` requires User Token (xoxp-). Other commands default to Bot Token (xoxb-)
- `history` / `thread` accept `--as-user` to read with the User Token instead
- `dms` lists your DM `D...` ids (User Token, `im:read`) — DMs have no name to resolve

## ⚠️ Breaking change (0.2.0) — `search` 출력의 `user`

`search` 출력에서 **`user` 가 핸들이 아니라 user id (`U…`) 로 바뀌었다.** 핸들은 새로
생긴 `username` 키로 간다.

```jsonc
// 0.1.0                        // 0.2.0
{ "user": "isutal" }            { "user": "U01E8PW8Q7K", "username": "isutal" }
```

**왜 바꿨나**: `history` / `thread` 는 처음부터 `user` 가 id 였다. `search` 만 핸들이라
같은 CLI 안에서 같은 키가 다른 걸 뜻했다. 이제 세 커맨드 전부 `user` = id 다.

**작성자로 필터링할 거면 `user`(id) 를 써라.** 핸들은 바뀌고, 봇은 `users.list` 에 안
나와서 id 목록만이 신뢰할 수 있는 키다. 앱/연동 포스트는 id 가 없어 `user` 가 빈 문자열
이고 `username` 만 있다 — 이건 계정이 아니라 연동이라는 신호다.

## 어느 토큰으로 읽을 것인가 — `--as-user`

**Bot token 은 봇이 초대된 채널만 본다.** private 채널은 `channel_not_found`,
초대 안 된 채널은 `not_in_channel` 로 실패한다. 조용한 실패가 아니라 에러로 오지만,
"멘션을 받았는데 그 채널을 읽을 수 없다" 는 상황이 흔하다.

`--as-user` 는 User Token 으로 읽어 **토큰 소유자가 속한 모든 채널**을 커버한다.
채널 초대가 필요 없다. 대신 필요한 user scope 가 있다:

| scope | 없으면 |
|---|---|
| `channels:history` | public 채널 못 읽음 |
| `groups:history` | private 채널 못 읽음 |
| `im:history` / `mpim:history` | DM / 그룹DM 못 읽음 |
| `im:read` | `dms` 로 DM 목록(=`D...` id) 을 못 얻음 |

**언제 쓰나**: "내가 이 스레드에 답했나" 처럼 **사람 관점**으로 대화를 봐야 할 때.
봇 관점(봇이 참여한 채널만)으로 충분하면 default 를 쓴다.

**`#채널명` 은 bot token 으로 resolve 된다** (user token 에 보통 `channels:read` 가 없다).
bare id (`C...` public / `G...` private·그룹DM / `D...` DM) 를 넘기면
`resolve_channel` 이 short-circuit 되어 bot token 없이도 동작한다.

**DM 은 반드시 `D...` id 로 넘겨야 한다.** DM 은 `conversations.list` 의 public/private
타입에 안 나와서 이름으로 resolve 할 방법이 없다. id 는 `dms` 로 열거하거나 `search`
결과의 `channel_id` 에서 얻는다.

**default 를 바꾸지 않은 이유**: 기존 호출자(예: context-central 의 `history`/`thread` cron)
동작이 변하면 안 된다. opt-in 이어야 한다.

## Slack Lists (`lists:read`)

`lists items <LIST>` / `lists comments <LIST>` read Slack Lists. `<LIST>` accepts either
a bare list id (`F...`) or the full Slack Lists URL (the id is the last path segment).

| 사실 | 왜 중요한가 |
|---|---|
| **USER 토큰(xoxp-) 전용.** `--as-user` 옵션이 없다 — 이 명령군은 유저 토큰이 유일한 선택지다. | BOT 토큰은 `list_not_found` 로 실패한다 (리스트가 다른 워크스페이스 소속일 수 있어서). 조용한 0건이 아니라 stderr 한 줄 메시지와 함께 에러로 죽는다 — 그래도 토큰을 잘못 고르기 쉬운 지점이라 표로 남긴다. |
| `slackLists.info` API가 없다. | **컬럼의 사람이 읽을 이름을 얻을 방법이 없다.** 출력은 `column_id` 로만 필드를 식별한다 — 이름을 지어내지 않는다. |
| 값이 빈 필드는 API 응답의 `fields` 배열에서 아예 빠진다. | "담당자 미지정" 같은 판정은 그 `column_id` 의 **부재**로 해야 한다. item 마다 `fields` 길이가 다른 게 정상이다. |
| `lists comments` 의 코멘트 채널 id 는 리스트 id 의 첫 글자를 `F`→`C` 로 바꿔 유도한다. | **리스트 1건에서만 관측**했다 — 문서화된 규칙이 아니다. 출력에 `comment_channel`/`derived` 를 항상 넣고, 채널 조회가 실패하면 조용히 빈 배열을 주지 않고 에러로 죽는다. |

## Search Modifiers

Slack 검색 문법 사용 가능:
- `in:#channel-name` — 특정 채널에서 검색
- `from:@username` — 특정 사용자 메시지
- `before:2026-01-01` / `after:2026-01-01` — 날짜 범위
- `has:link` / `has:emoji` — 필터
