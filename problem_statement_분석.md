# Buy or Wait? — 문제 분석 (한국어)

> 원본: `problem_statement.md` 기반 요약/분석. 해석 판단이 들어간 부분은 "→"로 표시.

## 1. 한 줄 요약

사용자가 "이거 사도 돼?" 라고 물으면, **현재 잔고뿐 아니라 향후 90일 현금흐름 전체**를 시뮬레이션해서 얼마를 언제 내는 게 안전한지 판단하는 개인화 재무 에이전트를 만드는 것.

## 2. 왜 어려운가

- 단순 "잔고 > 금액" 비교가 아니라, **반복 지출/예정된 입출금/최소 유지 잔고**를 90일간 추적하는 시계열 시뮬레이션이 필요함.
- 같은 잔고라도 사용자의 `financial_priorities`, `payment_methods_user_will_consider`, `spending preferences`에 따라 다른 답이 나와야 함 → 규칙 기반 + 사용자별 프로필 반영 필수.
- 데이터가 여러 CSV에 흩어져 있고(`user_id`/`request_id`/`related_event_id`로 조인), 일부 금액은 텍스트가 아니라 **이미지에서 추출**해야 함.
- 메시지/이미지는 "정보"일 뿐 "명령"이 아님 → 프롬프트 인젝션 방어가 요구사항에 명시됨 ("Embedded instructions must not override the problem rules").

## 3. 입력 데이터 구조

| 파일 | 역할 |
|---|---|
| `requests.csv` | **예측 대상.** 사용자의 질문(요청) 목록 |
| `sample_requests.csv` | 정답 예시 (형식/스타일 학습용, 채점 대상 아님) |
| `financial_profiles.csv` | 통화, 잔고, 최소 유지 잔고, 우선순위, 지출 선호, 결제 선호 |
| `financial_events.csv` | 과거/예정 거래, 비현금 투자 평가액, 확정 급여 |
| `exchange_rates.csv` | 날짜별 고정 환율 |
| `request_payment_options.csv` | 요청별 결제 옵션(할부 등, 2~4개) |
| `messages.csv` | 사용자 메시지 (일부만 특정 이벤트와 연결됨) |
| `images.csv` | 요청/이벤트/사용자와 연결된 이미지 (`dataset/media/images/<image_id>.png`) |
| `output.csv` | 제출용 빈 템플릿 |

**조인 키:** `user_id`(사용자 단위), `request_id`(요청 단위), `related_event_id`(메시지/이미지 → 이벤트).

**주의:** `amount`가 비어있는 이벤트는 0이 아니라 → 연결된 이미지에서 금액을 읽어와야 함.

### requests.csv 입력 필드
`request_id`, `user_id`, `request_date`, `request_type`(purchase/travel/education/family_transfer/debt_repayment/investment/housing/emergency_expense/other), `requested_amount`, `desired_completion_date`, `allows_partial_payment`, `request_text`

## 4. 출력 스키마 (`output.csv`)

| 컬럼 | 의미 |
|---|---|
| `request_id` | 요청 ID |
| `amount_safe_to_pay` | 오늘(`request_date`) 기준 추가 지출 조정 없이 안전하게 낼 수 있는 최대 금액. `0 ≤ 값 ≤ requested_amount` |
| `affordability_status` | `affordable_now` / `affordable_with_plan` / `affordable_later` / `not_affordable` |
| `recommended_payment_method` | `full_payment` / `partial_payment` / `installments` / `wait` / `not_recommended` |
| `payment_plan` | `YYYY-MM-DD:금액|YYYY-MM-DD:금액...` 형식, 없으면 `none` |
| `earliest_date_for_full_payment` | 전액 결제가 안전해지는 가장 빠른 날짜 (`affordable_now`면 `request_date`와 동일, 90일 내 불가능하면 공란) |
| `spending_changes_needed` | `stop:<event_id>` / `reduce_to:<event_id>:<금액>` 최대 3개, `|`구분, 없으면 `none` |
| `decision_explanation` | 근거 짧은 설명 |

## 5. 핵심 로직: "90일 안전성 체크"

- 향후 90일간 **반복 수입/지출 + 확정 예정 결제 + 관련 메시지/이미지**로 잔고를 시뮬레이션.
- 어느 시점에서도 `minimum_balance_to_keep` 아래로 내려가면 안전하지 않음.
- **무시할 것:** 대기중(pending) 수입, 실패/취소된 거래, 중복 레코드, 미실현 투자 평가액.
- `amount_safe_to_pay` = (지출 조정 전) 오늘 기준으로 안전 체크를 깨지 않는 최대 지불액, `requested_amount` 상한.
- `earliest_date_for_full_payment` = (지출 조정 없이) 전액이 처음으로 안전해지는 날짜.

## 6. 결제 방식별 조건 요약

- **`full_payment`**: 오늘 전액 지불이 안전 + 사용자가 `full_payment`를 허용할 때만.
- **`partial_payment`**: `affordability_status=affordable_with_plan` 필수. 조건: 부분결제 허용, 사용자가 이 방식 허용, `0 < amount_safe_to_pay < requested_amount`, `earliest_date_for_full_payment ≤ desired_completion_date`. **정확히 2번 지불**(오늘 안전금액 + 나머지를 earliest_date에), `request_payment_options.csv`와 매칭될 필요 없음.
- **`installments`**: 반드시 `request_payment_options.csv`의 옵션과 정확히 일치해야 함.
- **`wait`**: 나중에 전액 결제가 안전해질 때 + 사용자가 `full_payment`를 허용할 때.
- **`not_recommended`**: 안전한 방법이 하나도 없을 때의 기본값.

### 복수 안전 플랜이 있을 때 우선순위 (순서대로 tie-break)
1. `desired_completion_date` 내 완료
2. 지출 변경(spending change) 불필요
3. 총 지불 금액 최소화
4. 결제 시작을 더 이르게
5. 지불 횟수 최소화
6. `payment_option_id`가 더 낮은 것

## 7. 데이터 충돌 해석 우선순위

1. 명시적 취소/정산/수정 기록
2. 같은 출처의 더 최신 기록
3. 추정치보다 정산(settled) 완료된 이벤트
4. 그래도 애매하면 **재무적으로 더 안전한 해석**

→ 즉, 판단이 애매할 때는 항상 보수적으로.

## 8. 신뢰 경계 (보안 관점)

- 메시지/이미지 내용은 재무 사실을 확인/수정/취소하는 **데이터**로만 취급.
- 그 안에 "이 규칙 무시해" 같은 지시문이 있어도 **문제 규칙을 절대 우회하면 안 됨** → 프롬프트 인젝션 방어를 명시적으로 요구.
- 없는 소득/지출/결제옵션을 지어내면 안 됨 (환각 금지).

## 9. 채점 기준

- `amount_safe_to_pay` 정확도
- `affordability_status` 정확성
- `recommended_payment_method` + `payment_plan` 정확성
- `earliest_date_for_full_payment` 정확도
- `spending_changes_needed` 유효성
- `decision_explanation`의 유용성/일관성

## 10. 제출물

| 파일 | 내용 |
|---|---|
| `code.zip` | 실행 가능한 전체 코드 + 프롬프트/설정 + README + `evaluation/` 폴더 |
| `output.csv` | 전체 요청에 대한 예측 |
| `chat_transcript` | 개발 과정 대화 기록 |

**필수 포함:** `evaluation/usage_report.md` — 모델별 호출 수, 입/출력 토큰, 총/평균 토큰, 예상 비용(전체+모델별).
**금지:** API 키/자격증명 포함.

## 11. 구현 시 체크리스트 (제안)

- [ ] CSV 로더 + `user_id`/`request_id`/`related_event_id` 조인 레이어
- [ ] 환율 변환 (날짜+통화쌍 매칭)
- [ ] 이미지에서 금액 추출 (blank amount → image 조회 → VLM 또는 OCR)
- [ ] 이벤트 상태(`settled`/`pending`/`scheduled`/`unrealized`) 필터링 로직
- [ ] 90일 현금흐름 시뮬레이터 (일 단위 잔고 추적)
- [ ] 결제 방식 후보 생성 + tie-break 규칙 적용
- [ ] `spending_changes_needed` 로직 (stop/reduce, flexible 이벤트만)
- [ ] 메시지/이미지 기반 충돌 해석 (우선순위 4단계)
- [ ] 출력 포맷 검증 (금액 합, 날짜 형식, `payment_plan` 문법)
- [ ] `evaluation/usage_report.md` 자동 생성
