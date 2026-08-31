---
ticket: LOCAL-20260824
task_id: task-1-lists-read
plan_sha: (no plan.md — free-text path)
intent_problem: |
  Slack 리스트(Slack Lists)가 팀의 아젠다 수합 창구로 쓰이는데 slack-tools 에 읽는 명령이 없어, 호출자가 매번 raw curl 로 slackLists API 를 직접 치고 커서 페이지네이션·필드 파싱을 재구현한다.
contributes_to: lists 명령군 신설 — items 조회 + 코멘트 조회 2개 서브커맨드
---

# Task 1: `slack-tools lists` 명령군 신설

> Ticket: LOCAL-20260824
> Phase: 1
> Branch: feat/LOCAL-20260824-slack-lists-read
> Runner: in-session
> Depends on: none

## 사용자 최초 프롬프트 원문

```
문서 정정해주고 SLACK-TOOLS에 명령 넣는건 작업해줘 대신 서브에이전트에서 impl써서 작업 및 리뷰핑퐁 잘 하고..
```

(직전 맥락: `lists:read` scope 가 새로 들어와 Slack 리스트를 읽을 수 있게 됐고, 실제로 raw curl
로 읽는 데 성공했다. 그 경로를 CLI 로 승격하는 작업이다.)

## 사전 준비

| 파일 | 읽는 목적 |
|---|---|
| `CLAUDE.md` | 토큰 선택 규율(`--as-user`), JSON 출력 규약, breaking change 기술 방식 |
| `src/slack_tools/cli.py` | click 그룹·커맨드 등록 패턴, lazy import 관행, `_read_client` 헬퍼 |
| `src/slack_tools/queries.py` | read-only 함수는 **JSON 문자열을 반환**한다는 규약, 커서 페이지네이션 관행(`list_dms`/`search_messages`), `_SEARCH_PAGE_SIZE` 류 상수 주석 스타일 |
| `src/slack_tools/client.py` | `get_user_client` / `get_bot_client` / `is_channel_id` 시그니처 |
| `tests/test_dms.py` · `tests/test_search.py` | 테스트 스타일 — `MagicMock` 클라이언트 + `CliRunner`, `_pages()` 커서 헬퍼 |

## 실측 사실 (2026-08-24, 실제 API 응답으로 확인. 추측 아님)

**이 절의 내용은 이미 검증된 것이다. 다시 API 를 호출해 확인할 필요 없다 (토큰이 없을 수도 있다).**

1. 엔드포인트는 **`slackLists.items.list`** 다. slack-sdk `WebClient` 에 전용 메서드가 없으므로
   `client.api_call("slackLists.items.list", params={...})` 로 호출한다.
2. **USER 토큰(xoxp-)만 동작한다.** BOT 토큰은 `ok:false, error:"list_not_found"` 를 준다
   (리스트가 다른 워크스페이스 소속인 경우가 있어서다). 즉 이 명령군은 `--as-user` 옵션이 아니라
   **USER 토큰이 기본이자 유일**이다.
3. 파라미터: `list_id` (필수), `limit`, `cursor`. 응답은
   `{"ok":true, "items":[...], "response_metadata":{"next_cursor":"..."}}`.
   커서가 빈 문자열이면 끝이다.
4. **`slackLists.info` 는 존재하지 않는다** — `{"ok":false,"error":"unknown_method"}`.
   따라서 **컬럼의 사람이 읽을 이름을 얻을 방법이 없다.** `column_id` 만 노출한다.
   컬럼 이름을 지어내거나 추측해서 채우지 마라.
5. item 한 건의 실제 모양 (값은 합성으로 바꿨다):

```jsonc
{
  "id": "Rec0XXXXXXXXX",
  "list_id": "F0XXXXXXXXX",
  "date_created": 1787016086,          // epoch seconds (int)
  "created_by": "U0000000001",
  "updated_by": "U0000000002",
  "updated_timestamp": "1787016087",   // 문자열로 온다 (date_created 는 int)
  "fields": [
    { "key": "name", "column_id": "Col0A",
      "value": "[{\"type\":\"rich_text\",...}]",   // JSON 문자열
      "text": "안건 제목",
      "rich_text": [ /* 블록 배열 */ ] },
    { "key": "Col0B_alias", "column_id": "Col0B",
      "value": "U0000000003", "user": ["U0000000003"] },
    { "key": "Col0C_alias", "column_id": "Col0C",
      "value": "2026-08-18", "date": ["2026-08-18"], "timestamp": [-1] },
    { "key": "todo_completed", "column_id": "Col00",
      "value": false, "checkbox": false }
  ]
}
```

**필드에서 반드시 알아야 할 세 가지:**

- `key` 와 `column_id` 는 **서로 다른 값**이다 (`key` 가 다른 `Col…` 문자열인 경우가 있다).
  둘 다 보존한다. 안정적인 조회 키는 `column_id` 다.
- **값이 빈 필드는 `fields` 배열에서 아예 빠진다.** 그래서 item 마다 `fields` 길이가 다르다.
  "담당자 미지정" 을 판정하려면 그 `column_id` 가 없는 것을 보고 판단해야 한다.
- 타입 판별용 키가 값과 함께 온다: `text`/`rich_text`(텍스트) · `user`(사람) · `date`(날짜) ·
  `checkbox`(체크박스) · `select`(선택). `value` 는 원본이고 타입 키가 파싱된 결과다.

6. 🔑 **리스트에는 코멘트가 달리고, 그 코멘트는 별도 pseudo-channel 에 쌓인다.**
   실측: 리스트 `F0BG5933VUY` 의 코멘트가 채널 **`C0BG5933VUY`** 에 있었다 —
   접두 한 글자만 `F`→`C` 로 다른 같은 접미사다. `conversations.history` 로 그냥 읽힌다
   (USER 토큰 + `channels:history`). 각 item 생성 시 `USLACKBOT` 의 `"A comment was added"`
   메시지가 하나 생기고, **사람이 쓴 코멘트는 그 메시지의 스레드 답글**로 달린다.
   ⚠️ **이 `F`→`C` 규칙은 리스트 1건에서만 관측했다.** 규칙이라고 단정하지 말고 아래 지시대로
   *유도해서 시도하고, 실패하면 크게 실패*하도록 만들어라.

## 작업 내용

### 1. `src/slack_tools/queries.py` — 조회 함수 2개 추가

```python
def list_items(client: WebClient, list_id: str, limit: int = 0) -> str
def list_comments(client: WebClient, list_id: str, limit: int = 0) -> str
```

- 기존 규약대로 **JSON 문자열을 반환**한다 (`json.dumps(..., indent=2, ensure_ascii=False)`).
- `list_items`:
  - `client.api_call("slackLists.items.list", params={"list_id":…, "limit":…, "cursor":…})`
  - `limit == 0` 이면 커서를 끝까지 걷는다. 0 이 아니면 그 건수에서 멈춘다.
    (`search_messages` / `channel_history` 의 `0 = all` 규약과 동일하게)
  - 응답 `ok` 가 false 면 `error` 를 담은 예외/에러 종료로 **소리내어 실패**한다. 빈 배열 반환 금지.
  - 각 item 을 아래로 정규화한다. **필드 정보를 버리지 마라** — `CLAUDE.md` 가 지적한
    `history`/`thread` 의 화이트리스트 누락(`files` 가 빠져 첨부 유무조차 안 보임)과 같은 실수다.

```jsonc
{
  "id": "...", "list_id": "...",
  "created_by": "...", "date_created": 1787016086,
  "updated_by": "...", "updated_timestamp": "1787016087",
  "fields": [
    { "column_id": "Col0A", "key": "name", "type": "text",
      "value": "안건 제목", "raw": <원본 value> }
  ]
}
```
  - `type` 은 위 §5 의 타입 키 존재로 판정 (`text`/`user`/`date`/`checkbox`/`select`).
    아는 타입 키가 하나도 없으면 `type: "unknown"` 으로 두고 `raw` 를 그대로 보존한다.
    **모르는 타입을 조용히 버리지 마라.**
  - `user`/`date` 처럼 배열로 오는 타입은 배열을 유지한다 (다중 선택 가능성).

- `list_comments`:
  - `list_id` 의 **첫 글자를 `C` 로 바꿔** 코멘트 채널 id 를 유도한다.
  - `conversations_history` 로 그 채널을 읽고, `reply_count > 0` 인 메시지마다
    `conversations_replies` 로 스레드를 붙인다.
  - 출력 최상위에 **어떤 채널 id 를 유도해서 썼는지 반드시 넣는다**:
    `{"list_id": …, "comment_channel": "C…", "derived": true, "messages": [...]}`
  - 채널 조회가 실패하면 **에러로 죽인다.** 유도가 틀렸을 가능성을 메시지에 적는다. 예:
    `Error: comment channel C… not reachable (derived from list id; this F→C mapping is observed, not documented)`.
    조용히 빈 배열을 돌려주면 "코멘트가 없다" 와 구분이 안 된다 — 그게 이 작업에서 최악의 실패다.

### 2. `src/slack_tools/cli.py` — `lists` 그룹 추가

```
slack-tools lists items <LIST> [--limit N]
slack-tools lists comments <LIST> [--limit N]
```

- `@main.group()` 으로 `lists` 그룹을 만든다 (`usergroups` 처럼 단일 커맨드가 아니라 그룹이다).
- `<LIST>` 는 **리스트 id(`F…`) 와 Slack 리스트 URL 둘 다** 받는다.
  URL 예: `https://<any>.slack.com/lists/T0GCQMN07/F0BG5933VUY` → `F0BG5933VUY` 추출.
  사람이 Slack UI 에서 복사하는 것은 URL 이라서다. 파싱 헬퍼는 `client.py` 의
  `is_channel_id` 옆에 `parse_list_id(value: str) -> str` 로 둔다.
- **두 커맨드 모두 `get_user_client()` 를 쓴다.** `--as-user` 플래그를 추가하지 마라.
- `--limit` 기본값은 `0` (전체). 리스트는 보통 수십 건이라 잘릴 위험이 실익보다 크다.
- docstring 에 "requires SLACK_USER_TOKEN with lists:read" 를 적는다 (기존 커맨드 docstring 관행).

### 3. `tests/test_lists.py` 신설

기존 스타일(`MagicMock` + `CliRunner`)로 아래를 커버한다:

- `list_items` 가 커서를 끝까지 걷는다 (`limit=0`, 2페이지 mock)
- `limit=N` 이 N 건에서 멈춘다
- 빈 필드가 빠진 item 에서 존재하는 필드만 정규화된다 (item 마다 `fields` 길이가 다른 경우)
- `key != column_id` 인 필드에서 둘 다 보존된다
- 타입 판정: `text` / `user` / `date` / `checkbox` 각 1건 + **알 수 없는 타입이 `unknown` 으로 보존**
- `ok:false` 응답이 **조용히 통과하지 않는다** (예외 또는 non-zero exit)
- `parse_list_id` 가 URL 과 bare id 양쪽을 처리한다
- `list_comments` 가 유도한 채널 id 를 출력에 담는다
- `list_comments` 가 채널 조회 실패 시 **소리내어 실패**한다 (빈 배열 반환이 아니다)

### 4. `CLAUDE.md` 에 절 추가

`## Slack Lists (`lists:read`)` 절을 만들어 아래를 적는다. **문장은 짧게, 표를 쓴다.**

- USER 토큰 전용이고 BOT 은 `list_not_found` 라는 것 (이게 조용한 0건의 원인이 될 자리다)
- `slackLists.info` 가 없어서 **컬럼 이름을 얻을 수 없다** → `column_id` 로만 다뤄야 한다
- 빈 필드는 배열에서 빠진다 → "미지정" 판정은 부재로 한다
- 코멘트 pseudo-channel `F…`→`C…` 유도는 **리스트 1건에서만 관측했다**고 명시한다.
  단정하지 마라.

## Acceptance Criteria

```bash
cd /home/prasuer/sbx-work/slack-tools
uv run --with pytest --with click --with python-dotenv --with slack-sdk pytest tests/ -q
uv run --with ruff ruff check src/ tests/
uv run --with ruff ruff format --check src/ tests/ || true
uv run --with click --with python-dotenv --with slack-sdk python -c "
from click.testing import CliRunner
from slack_tools.cli import main
r = CliRunner().invoke(main, ['lists', '--help'])
assert r.exit_code == 0, r.output
assert 'items' in r.output and 'comments' in r.output, r.output
r2 = CliRunner().invoke(main, ['lists', 'items', '--help'])
assert r2.exit_code == 0 and '--limit' in r2.output, r2.output
print('cli wiring ok')
"
uv run --with click --with python-dotenv --with slack-sdk python -c "
from slack_tools.client import parse_list_id
assert parse_list_id('F0BG5933VUY') == 'F0BG5933VUY'
assert parse_list_id('https://krafton.enterprise.slack.com/lists/T0GCQMN07/F0BG5933VUY') == 'F0BG5933VUY'
print('parse_list_id ok')
"
grep -q 'lists:read' CLAUDE.md
```

`PYTHONPATH=src` 가 필요하면 붙여라. editable 설치가 이미 있으면 `uv run` 없이 그냥
`python -m pytest` 로도 된다 — **AC 는 실제로 통과하는 형태로 조정해서 실행하고,
실행한 명령 그대로**를 `.claude/runs/LOCAL-20260824/test-output.log` 에 append 한다.

## 주의사항

- **`git commit` / `git push` 를 하지 마라.** 이유: commit 은 orchestrator 소관이고, 이 레포는
  직전 런에서 implementer 자동 커밋이 앞선 작업을 통째로 삼킨 이력이 있다.
  atomic slice 라도 예외 없다. 변경 후 `git status` 만 보고하고 멈춘다.
- **컬럼의 사람이 읽을 이름을 만들어내지 마라.** 이유: `slackLists.info` 가 없어서 확인할 방법이
  없다. 추측한 이름이 들어가면 호출자가 그걸 사실로 믿는다.
- **`F`→`C` 코멘트 채널 유도를 "문서화된 규칙"처럼 쓰지 마라.** 이유: 리스트 1건에서만 관측했다.
  유도한 값을 출력에 노출하고 실패 시 크게 실패해야 오검을 사람이 잡을 수 있다.
- **필드를 화이트리스트로 잘라내지 마라.** 이유: `history`/`thread` 가 `files` 를 잘라내서
  "첨부가 있는지조차 안 보이는" 문제를 이미 만들었다. 같은 실수를 반복하는 것이다.
- **`--as-user` 플래그를 추가하지 마라.** 이유: BOT 토큰은 이 API 에서 `list_not_found` 로
  실패한다. 선택지가 아닌 것을 선택지처럼 노출하면 조용한 실패를 부른다.
- **기존 커맨드(`search`/`history`/`thread`/`dms`/`post`/`reply`)의 동작을 바꾸지 마라.**
  이유: `context-central` 의 cron 과 `prx-workspace` 스킬이 현재 출력 형태에 의존한다.
- **실제 Slack API 를 호출하지 마라.** 이유: 토큰이 이 세션에 없을 수 있고, 있어도
  `my-work-assistant` 와 rate limit 을 공유한다. 테스트는 전부 mock 으로 한다.

## On completion

`.claude/tasks/done/task-1-lists-read-result.md` 를
`~/.claude/templates/workflow-contract/result.schema.md` 에 따라 작성한다.
