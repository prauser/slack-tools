# slack-tools — 구현 계획서

## 개요

AI 에이전트 및 자동화를 위한 Slack CLI.
jira-tools와 동일한 패턴: Click CLI, JSON 출력, 환경변수 인증.

## 아키텍처

```
slack-tools/
├── src/slack_tools/
│   ├── __init__.py
│   ├── cli.py          # Click 엔트리포인트
│   ├── client.py       # WebClient 팩토리 (user/bot token)
│   ├── queries.py      # 읽기 전용 (search, history, thread, users)
│   └── actions.py      # 쓰기 (post, reply, react, upload)
├── tests/
│   ├── test_cli.py
│   ├── test_queries.py
│   └── test_actions.py
├── pyproject.toml
├── CLAUDE.md
└── .env.example
```

## 인증

| Token | 환경변수 | 용도 |
|-------|----------|------|
| User Token (xoxp-) | `SLACK_USER_TOKEN` | search (search.messages API는 user token 필요) |
| Bot Token (xoxb-) | `SLACK_BOT_TOKEN` | history, post, reply 등 나머지 전부 |

## 구현 단계

### Phase 1: 핵심 CLI (현재 완료)
- [x] 프로젝트 구조 (src-layout, pyproject.toml, click)
- [x] client.py — WebClient 팩토리, resolve_channel 헬퍼
- [x] `search` — 메시지 검색 (user token)
- [x] `history` — 채널 최근 메시지 (--since 지원)
- [x] `thread` — 스레드 전체 조회
- [x] `post` — 채널 메시지 전송
- [x] `reply` — 스레드 답장
- [x] CLAUDE.md

### Phase 2: 사용자 정보 & 채널 조회
- [x] `users` — 사용자 목록/검색 (이름 → ID 변환용)
- [x] `channels` — 채널 목록 (이름, ID, member count)
- [x] `usergroups` — 사용자 그룹 목록 및 멤버 조회
- [x] client.py에 `resolve_user(name_or_id)` 헬퍼 추가

### Phase 3: 추가 액션
- [ ] `react` — 이모지 리액션 추가/제거
- [ ] `upload` — 파일 업로드
- [ ] `update` — 기존 메시지 수정
- [ ] `delete` — 메시지 삭제
- [ ] `pin` / `unpin` — 메시지 고정

### Phase 4: 고급 검색 & 필터
- [ ] `search`에 날짜 범위 자동 변환 (--since, --until 옵션)
- [ ] `history`에 --user 필터, --has-thread 필터
- [ ] `search`에 --channel, --from 옵션 (Slack 검색 수식어 자동 조합)
- [ ] 검색 결과에 스레드 컨텍스트 포함 옵션

### Phase 5: 테스트 & 안정화
- [ ] queries.py 단위 테스트 (API mock)
- [ ] actions.py 단위 테스트
- [ ] CLI 통합 테스트 (click.testing.CliRunner)
- [ ] 에러 핸들링 통일 (rate limit, token expired 등)

## 의존성

- Python 3.10+
- click (CLI 프레임워크)
- slack-sdk (Slack Web API)
- python-dotenv (환경변수 로드)

## context-agent 연동

```toml
# context-agent/pyproject.toml
[tool.uv.sources]
slack-tools = { path = "../slack-tools" }
```

배포 시: `pip install ../jira-tools ../slack-tools .` 로 일괄 설치.
