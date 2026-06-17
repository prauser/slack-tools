# my-work-assistant → slack-tools 범용화 제안 (기능 수합)

작성: 2026-06-17 · 출처: `../my-work-assistant/src/collectors/slack.py` 및 `src/bot/slack_*`

## 배경

`my-work-assistant`는 slack-tools를 의존성으로 **선언만** 하고 실제로는 안 쓴다
(`import slack_tools` 0건, `collectors/slack.py:9` docstring "Uses slack_tools.client
directly"는 stale). 대신 `slack_sdk.WebClient`를 직접 감싸 dual-token·retry·subteam·
i_replied 등을 자체 구현했다. 그 과정에서 **범용으로 slack-tools에 있으면 좋을 기능**을
다수 만들었고, slack-tools와 로직이 중복되며 일부는 버그를 유발했다(예: i_replied가
thread reply를 못 잡음).

이 문서는 그 기능들을 slack-tools에 **추가/수정**할 후보로 수합한다. 채택 여부·API
형태는 slack-tools 메인테이너 판단. my-work-assistant 쪽은 당장은 통합하지 않고
i_replied 버그만 로컬에서 작게 고친다(별건).

> 범용 아님(이관 대상 아님, 참고용): KST 타임존 윈도우 필터, digest intent/action_needed
> 분류, registry/exclude_authors 운영 정책 — 이건 앱 고유 로직이라 slack-tools 밖에 둔다.

---

## P1 — 정확성/스레드 인지 (i_replied 버그의 뿌리, 우선)

### 1. `search_messages` 결과에 `thread_ts` 복구해서 붙이기
- **현상**: `search.messages` 응답 match는 top-level `thread_ts`를 **안 준다**
  (my-work-assistant 저장 데이터 498/498건 누락 확인). 단, `permalink`에는
  `...?thread_ts=1780895959.331509&cid=...` 형태로 박혀 있다.
- **문제**: thread_ts가 없으면 "이 매치가 스레드 안 메시지인지" 판단 불가 →
  스레드 답글 추적·i_replied 계산이 전부 어긋난다.
- **제안**: `search_messages`가 각 match에 대해 permalink에서 `thread_ts`를 정규식
  복구(`thread_ts=([0-9.]+)`)해 `thread_ts`·`in_thread`(자기 ts≠thread_ts) 필드를
  채워 반환. (현재 queries.py:13 `search_messages`는 raw match 그대로 반환)
- **출처**: PRA-108 후속 i_replied 조사.

### 2. "내가(특정 사용자가) 이 스레드에 답했나" 헬퍼 + Slack "replied" 근접 신호 노출
- **배경 조사 결론**: Slack Web API에는 "인증 사용자가 답글 달았다"는 **네이티브 필드가
  없다**. Activity/Threads UI의 "replied" 배지는 클라이언트 계산. 근접 신호:
  - `reply_users` — **샘플**(불완전·봇 ID 섞임) → 판정용으로 불충분
  - `subscribed`(bool) — 답글 달면 자동 구독 → 좋은 상관이나 부정확(@멘션 자동구독,
    수동 팔로우/언팔로우로 어긋남)
  - `reply_count`/`reply_users_count`/`latest_reply`/`last_read` — 메타데이터
  - **신뢰 판정법** = `conversations.replies(thread_ts)`를 받아 `after_ts` 이후
    `user==대상`인 메시지 존재 확인. 이게 사실상 Slack이 "replied"를 도출하는 방식.
- **제안**:
  - `user_replied_after(client, channel, thread_ts, after_ts, user_id) -> bool`
    (authoritative 스캔)
  - `thread_replies`(queries.py:100) 응답에 부모 메시지의 `subscribed`·`reply_users`·
    `reply_users_count`·`latest_reply`도 포함(보조 신호, UI 근접용).
- **⚠️ 구현 시 필수 계약 (my-work-assistant가 실제로 밟은 함정 2개):**
  1. **`after_ts` 별로 평가, 스레드 단위로 캐시 금지.** "멘션1 → 내 답 → 멘션2(재멘션)"
     에서 멘션2 는 아직 안 답한 것이므로 False 여야 한다. (channel, thread_ts) 로만
     캐시하면 멘션1 의 True 가 멘션2 로 새어 재멘션을 "이미답함" 으로 오판한다.
     → 캐시 키에 반드시 `after_ts` 포함, 또는 thread 한 번 fetch 후 ts 별 in-memory 평가.
  2. **`reply_ts > after_ts` 엄격 비교를 코드로 강제.** Slack `oldest` 는 inclusive 라
     API 필터에만 의존하면 경계/재멘션에서 옛 답글이 잡힌다. `float(reply_ts) > float(after_ts)`
     명시 비교 + 원본 메시지 ts 자기 자신 skip.
- **출처**: `_compute_i_replied` (collectors/slack.py) + 재멘션 캐시 버그 픽스(2026-06-17).

### 3. 멘션 관련성 게이트 (search 과수집 필터)
- **현상**: `search.messages`로 `<@user>` 검색 시, **내가 멘션된 "스레드"의 형제
  메시지까지** 반환된다(my-work-assistant 실측 488건 중 386건=79%가 본문에 내 멘션
  토큰 없음).
- **제안**: 본문에 `<@user_id>`(라벨형 `<@id|name>` 포함) 또는 사용자가 속한
  `<!subteam^sid>`가 **실제로 있는** 메시지만 통과시키는 헬퍼
  `text_mentions_target(text, user_id, subteam_ids) -> bool` + search 옵션
  `--only-real-mentions`.
- **출처**: PRA-108, `_mentions_target` (collectors/slack.py:31-50).

---

## P2 — 클라이언트/인프라

### 4. dual-token 클라이언트 묶음
- search는 user token(xoxp), usergroups/post는 bot token(xoxb) 필요. 한 플로우에서
  둘 다 쓰는 경우가 많다. 현재 `client.py`의 `get_user_client`/`get_bot_client`는
  분리 팩토리뿐. **두 클라이언트를 함께 들고 다니는 컨텍스트/네임스페이스** 제공 제안.
- **출처**: my-work-assistant가 `SimpleNamespace(user_client=, bot_client=)`로
  자체 구성(backfill.py:131-135).

### 5. RateLimitErrorRetryHandler 기본 등록
- 429 Retry-After 자동 재시도 핸들러를 client 팩토리에서 **기본 등록**. 대량
  수집·페이지네이션에서 필수. (my-work-assistant는 모든 client에 등록 — PRA-53)
- **출처**: `_attach_rate_limit_retry` (collectors/slack.py:31~, PRA-53).

### 6. "사용자 X가 속한 subteam id" 조회 + 캐시
- `usergroups.list` + `usergroups.users.list`로 특정 user의 subteam id 목록 산출,
  exclude 지원, 디스크 캐시(TTL). 현재 `list_usergroups(include_members)`(queries.py:193)
  까지만 있음. **`my_subteam_ids(client, user_id, exclude=...)` 헬퍼** 제안.
- **출처**: `src/bot/slack_subteams.py` `SubteamMembership.my_subteam_ids` (F6/F6-FU).

### 7. 이름 해석 + 캐시 (raw ID → 사람이 읽는 이름)
- `users.info`로 display name 캐시, `<@U…>`/`<!subteam^S…>` 토큰을 사람이 읽는
  텍스트로 치환. 현재 `list_users`(queries.py:122)만. **resolver/캐시 헬퍼** 제안.
- **출처**: `src/bot/slack_names.py` NameResolver.

---

## P3 — 편의/엣지

### 8. broadcast 토큰 필터 유틸
- `<!channel>`/`<!here>`/`<!everyone>`(라벨 변형 포함) 감지 정규식. 공지성 노이즈
  제거용 공용 헬퍼.
- **출처**: `_BROADCAST_RE` (collectors/slack.py:28).

### 9. search `after:` off-by-one 보정
- Slack `after:`는 **배타적**(after:2026-05-27 → 5/28부터). 시작일 포함하려면 하루
  당겨 포맷해야 함. `search_messages`가 날짜 범위를 받을 때 내부 보정 + 문서화.
- **출처**: collectors/slack.py:256-263 주석.

### 10. DM/mpim 열거·수집
- `conversations.list(types="im,mpim")` + history. 현재 `channels`(queries.py:157)는
  public/private만. DM 채널 열거 지원 추가 제안.
- **출처**: `_collect_dm` (collectors/slack.py:338~).

---

## 정리: 채택 시 효과

- **P1(1·2·3)** 만 반영해도 my-work-assistant의 i_replied/멘션품질 로직을 slack-tools로
  수렴시킬 토대가 생기고, context-central의 thread_state 류 소비자도 공유 가능.
- **P2** 는 모든 slack-tools 소비자의 견고성(429·dual-token·subteam)을 올린다.
- 통합(my-work-assistant가 실제로 slack-tools를 쓰게 하는 것)은 **별도 티켓**으로,
  이 문서를 근거 삼아 단계적으로.
