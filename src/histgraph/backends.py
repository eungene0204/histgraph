"""추출 백엔드 — Claude API · 로컬 모델 · OpenRouter.

같은 프롬프트·스키마를 여러 경로에 태운다. 로컬 모델은 API 키도 비용도
필요 없어서 971건 벌크 추출에 맞고, Claude 는 품질 기준선 역할을 한다.
OpenRouter 는 **남의 GPU 를 무료 모델로 빌리는 길**이다 — 35GB 를 잡는
MLX 를 띄울 수 없는 자리(개인 역사를 화면에서 바로 물을 때)를 위한 것이다.

**핵심 차이: 구조화 출력 강제 수준.**
  - Claude: `output_config.format` 이 스키마를 강제한다. 파싱은 항상 성공.
  - ollama 0.30.7: `format` 에 스키마 객체를 줘도 **무시된다**(실측 —
    자유 산문이 돌아왔다). `format: "json"` 문자열만 JSON 모드를 켠다.
    형태는 보장되지 않으므로 클라이언트에서 검증하고 고쳐 받아야 한다.
  - OpenRouter: `response_format.json_schema` 를 **모델이 지원할 때만**
    강제된다. 무료 모델 19개 중 그것을 진짜로 지키는 것은 다섯이었다
    (2026-09-08 실측) — 나머지는 ollama 처럼 제 마음대로 낸다.

그래서 로컬 백엔드는 검증→재요청 루프를 갖는다. 이건 로컬 전용 우회가
아니라 방어로도 맞다 — 제약 디코딩이 걸려도 의미가 틀린 응답은 나온다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_LOCAL_MODEL = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q5_K_M"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# 무료 모델 가운데 한국어와 JSON 스키마가 함께 되는 것 (2026-09-08 실측:
# 무료 19개 중 dots-3-note 는 라벨을 중국어로 냈고, gemma 4 는 상류가 늘
# 429, nemotron-3.5-lightning·inkling 은 스키마를 아예 안 받는다).
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
ENV_OPENROUTER_KEY = "OPENROUTER_API_KEY"
ENV_OPENROUTER_MODEL = "OPENROUTER_MODEL"
# 무료 모델의 한도는 분당 20회다 (크레딧 $10 이상이면 하루 1,000회, 아니면
# 50회). 벌크로 부를 때 그 벽에 먼저 부딪히지 않도록 사이를 띄운다.
OPENROUTER_MIN_INTERVAL = 3.2


class Backend(Protocol):
    """추출 백엔드 공통 인터페이스."""

    name: str
    # 실제로 돌린 모델. 엣지에 이 값을 남긴다 — 어느 모델이 그 문장을
    # 판정했는지 모르면 나중에 틀린 엣지의 출처를 가릴 수 없다.
    model: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        """관계 목록을 돌려준다. 실패 시 빈 목록."""
        ...

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      max_tokens: int | None = None) -> dict | None:
        """스키마대로의 JSON 객체 하나. 관계 목록이 아닌 것(요약 한 편)을 받을 때.

        `max_tokens` 는 답의 크기가 요약 한 편과 다를 때 준다 — 개인 역사
        (`life`)의 JSON 은 절 열한 개라 기본값(800)에서 잘린다."""
        ...


def _coerce_relations(payload: Any) -> list[dict] | None:
    """모델이 낸 JSON 을 관계 목록으로 정규화.

    스키마가 강제되지 않으면 모델은 형태를 자주 흘린다. 실측된 변형:
      {"relations": [...]}        <- 기대한 형태
      [...]                        <- 배열만
      {"subject":..,"relation":..} <- 관계 하나를 통째로
    셋 다 받아준다. 형태가 조금 다른 것과 내용이 틀린 것은 다른 문제다."""
    if isinstance(payload, dict):
        if isinstance(payload.get("relations"), list):
            return payload["relations"]
        # 관계 객체 하나만 온 경우
        if {"subject", "relation", "object"} <= set(payload):
            return [payload]
        return None
    if isinstance(payload, list):
        return payload
    return None


def _extract_json(text: str) -> Any | None:
    """응답 텍스트에서 JSON 을 건져낸다.

    JSON 모드여도 앞뒤에 설명이나 ```json 펜스가 붙어 오는 경우가 있다."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 코드펜스 제거
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 가장 바깥 중괄호/대괄호 덩어리
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


class AnthropicBackend:
    """Claude API. 구조화 출력으로 스키마가 강제된다."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5", effort: str = "medium") -> None:
        self.model = model
        self.effort = effort
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      max_tokens: int | None = None) -> dict | None:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or 2000,
            system=system,
            output_config={
                "format": {"type": "json_schema", "schema": schema},
                "effort": self.effort,
            },
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            log.warning("거절됨: %s", response.stop_details)
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        payload = _extract_json(text)
        return payload if isinstance(payload, dict) else None

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=system,
            output_config={
                "format": {"type": "json_schema", "schema": schema},
                "effort": self.effort,
            },
            messages=[{"role": "user", "content": user}],
        )
        # 안전 분류기가 거절하면 content 가 비거나 부분적이다
        if response.stop_reason == "refusal":
            log.warning("추출 거절됨: %s", response.stop_details)
            return []
        text = next((b.text for b in response.content if b.type == "text"), "")
        payload = _extract_json(text)
        return _coerce_relations(payload) or []


class OllamaBackend:
    """로컬 모델 (ollama). 스키마가 강제되지 않으므로 검증하고 고쳐 받는다."""

    name = "ollama"

    def __init__(
        self,
        model: str = DEFAULT_LOCAL_MODEL,
        url: str = OLLAMA_URL,
        num_ctx: int = 16384,
        timeout: int = 600,
        max_repairs: int = 2,
    ) -> None:
        self.model = model
        self.url = url
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.max_repairs = max_repairs

    def _call(self, messages: list[dict]) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                # 추출은 창의성이 필요 없다. 재현성을 위해 0.
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0,
                    "num_ctx": self.num_ctx,
                    "num_predict": 4096,
                },
            }
        ).encode()

        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"ollama HTTP {err.code}: {detail}") from err
        except (urllib.error.URLError, TimeoutError) as err:
            raise RuntimeError(
                f"ollama 연결 실패 ({self.url}) — `ollama serve` 실행 중인지 확인: {err}"
            ) from err

        if data.get("done_reason") == "length":
            log.warning("응답이 길이 제한에 걸려 잘렸습니다 — num_predict 상향 필요")
        return data.get("message", {}).get("content", "")

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        # 스키마를 강제할 수 없으니 프롬프트에 형태를 명시한다
        shape = json.dumps(schema, ensure_ascii=False, indent=2)
        sys_prompt = (
            f"{system}\n\n"
            f"반드시 아래 JSON 스키마를 정확히 따르는 JSON 객체 **하나만** 출력하세요. "
            f"설명·머리말·코드펜스 없이 JSON 만 출력합니다.\n\n{shape}"
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ]

        for attempt in range(self.max_repairs + 1):
            text = self._call(messages)
            relations = _coerce_relations(_extract_json(text))
            if relations is not None:
                return relations

            if attempt < self.max_repairs:
                log.info("형태 불일치 — 재요청 %d/%d", attempt + 1, self.max_repairs)
                # 무엇이 틀렸는지 알려줘야 같은 실수를 반복하지 않는다
                messages = messages[:2] + [
                    {"role": "assistant", "content": text[:500]},
                    {
                        "role": "user",
                        "content": (
                            '위 응답은 형식이 틀렸습니다. {"relations": [...]} 형태의 '
                            "JSON 객체 하나만, 다른 텍스트 없이 출력하세요."
                        ),
                    },
                ]

        log.warning("형태 교정 실패 — 이 문서는 건너뜁니다: %s", text[:150])
        return []


DEFAULT_MLX_MODEL = "mlx-community/Qwen3.6-35B-A3B-8bit"


class MLXBackend:
    """로컬 MLX 모델 (Apple Silicon).

    ollama 와 달리 **스키마가 진짜로 강제된다** — outlines 가 JSON Schema 를
    유한상태기계로 컴파일해 매 토큰의 로짓을 마스킹하므로, 문법적으로
    스키마를 벗어나는 토큰이 애초에 샘플링되지 않는다. 파싱 실패가 없다.

    모델은 한 번만 올린다. 971건을 매번 로드하면 35GB 를 계속 다시 읽는다.
    """

    name = "mlx"

    def __init__(
        self,
        model: str = DEFAULT_MLX_MODEL,
        max_tokens: int = 12000,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._generator = None
        self._schema_key = None
        self._wrapped = None
        self._tokenizer = None

    def _build(self, schema: dict[str, Any]):
        """모델과 스키마 제약 생성기를 준비. 모델은 한 번, 생성기는 스키마마다
        한 번 — 한 프로세스가 관계 추출과 요약을 번갈아 물을 수 있게."""
        key = json.dumps(schema, sort_keys=True)
        if self._generator is not None and self._schema_key == key:
            return self._generator

        import outlines
        from outlines.types import JsonSchema

        if self._wrapped is None:
            from mlx_lm import load

            log.info("MLX 모델 로드 중: %s (최초 1회, 수십 초 소요)", self.model)
            model, tokenizer = load(self.model)
            self._tokenizer = tokenizer
            self._wrapped = outlines.from_mlxlm(model, tokenizer)
            log.info("MLX 모델 준비 완료")
        self._generator = outlines.Generator(self._wrapped, JsonSchema(schema))
        self._schema_key = key
        return self._generator

    def _chat_prompt(self, system: str, user: str) -> str:
        """모델의 채팅 템플릿을 적용한다.

        생 문자열을 넣으면 지시-튜닝된 모델이 제 성능을 못 낸다."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        tok = self._tokenizer
        apply = getattr(tok, "apply_chat_template", None)
        if apply is None:
            return f"{system}\n\n{user}"
        try:
            # Qwen3 계열은 사고 모드가 기본이다. 추출은 사고가 필요 없고
            # 사고 토큰이 max_tokens 를 잡아먹으므로 끈다.
            return apply(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
        except TypeError:
            return apply(messages, tokenize=False, add_generation_prompt=True)

    def _generate(self, system: str, user: str, schema: dict[str, Any],
                  max_tokens: int | None = None) -> Any | None:
        generator = self._build(schema)
        prompt = self._chat_prompt(system, user)
        try:
            text = generator(prompt, max_tokens=max_tokens or self.max_tokens)
        except Exception as err:  # 생성 실패는 문서 하나만 건너뛴다
            log.warning("MLX 생성 실패: %s", err)
            return None
        return _extract_json(text)

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      max_tokens: int | None = None) -> dict | None:
        # 요약 한 편은 짧다. 관계 추출의 12,000 토큰을 주면 잘못 샌 생성이
        # 그만큼 오래 돈다. 큰 답(개인 역사)은 부르는 쪽이 상한을 준다.
        payload = self._generate(system, user, schema, max_tokens=max_tokens or 800)
        return payload if isinstance(payload, dict) else None

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        payload = self._generate(system, user, schema)
        if payload is None:
            return []
        text = json.dumps(payload, ensure_ascii=False)
        relations = _coerce_relations(payload)
        if relations is None:
            # 스키마가 강제되므로 여기 오면 대개 max_tokens 로 잘린 것이다
            log.warning("스키마 강제에도 파싱 실패 (잘림 의심): %s", text[-120:])
            return []
        return relations


class OpenRouterBackend:
    """OpenRouter — 남의 GPU 를 무료 모델(`:free`)로 빌린다.

    MLX 를 못 띄우는 자리를 위한 길이다. 화면에서 이야기를 넣으면
    (`server.LifeAnalysis`) 35GB 를 잡는 로컬 모델 대신 이쪽으로 묻는다.

    실측에서 나온 함정 넷을 여기서 막는다 (2026-09-08):

    - **오류가 HTTP 200 으로 온다.** 상류가 막히면 몸에 `{"error": ...}` 가
      담겨 오고 `choices` 가 아예 없다. 상태 코드만 보면 빈 답을 정답으로
      읽는다 (공공데이터 API 와 같은 함정).
    - **사고(reasoning)를 끄지 않으면 답이 안 나온다.** nemotron 은 12,000
      토큰 가운데 10,615 를 사고에 쓰고 잘렸다(`finish_reason: length`).
      끄면 같은 이야기를 5,476 토큰에 냈다. 그래서 기본이 꺼짐이고, 못 끄는
      모델(liquid 는 400 으로 거절한다)만 켜고 다시 부른다.
    - **분당 20회.** 벌크로 부르면 그 벽이 먼저 온다 — 호출 사이를 띄운다.
    - **모델이 스키마를 안 받기도 한다.** strict → 느슨 → JSON 모드 순으로
      물러난다. 그래도 형태가 틀릴 수 있으므로 부르는 쪽이 검증한다
      (`life.validate`).

    열쇠는 `.env` 의 `OPENROUTER_API_KEY`, 모델은 `OPENROUTER_MODEL` 이다.
    """

    name = "openrouter"

    # 여러 스레드가 같이 부를 수 있다 (서버). 한도는 계정마다이므로 자물쇠도 하나다.
    _gate = threading.Lock()
    _last_call = 0.0

    def __init__(
        self,
        model: str | None = None,
        key: str | None = None,
        timeout: int = 900,
        retries: int = 3,
    ) -> None:
        self.model = model or os.environ.get(ENV_OPENROUTER_MODEL, "").strip() or DEFAULT_OPENROUTER_MODEL
        self.key = (key if key is not None else os.environ.get(ENV_OPENROUTER_KEY, "")).strip()
        self.timeout = timeout
        self.retries = retries
        # 이 모델이 사고를 끌 수 없다고 답했는지. 한 번 배우면 다시 안 묻는다.
        self.reasoning_locked = False
        # 마지막으로 실패한 까닭. 답이 안 왔을 때 **화면이 왜인지 말할 수 있게**
        # 남긴다 (`server.model_silence`). 로그는 배포에서 사람이 못 본다.
        self.last_error = ""

    # --- 부르기 ---------------------------------------------------------
    def _throttle(self) -> None:
        with OpenRouterBackend._gate:
            wait = OPENROUTER_MIN_INTERVAL - (time.monotonic() - OpenRouterBackend._last_call)
            if wait > 0:
                time.sleep(wait)
            OpenRouterBackend._last_call = time.monotonic()

    def _post(self, body: dict) -> tuple[dict | None, str]:
        """한 번 부른다. (답, 오류 설명) — 답이 None 이면 오류 설명이 있다."""
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                # OpenRouter 가 어디서 온 부름인지 적는 자리. 열쇠와 달리
                # 비밀이 아니다.
                "HTTP-Referer": "https://www.histgraph.space",
                "X-Title": "histgraph",
            },
        )
        self._throttle()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")[:300]
            return None, f"HTTP {err.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            return None, f"연결 실패: {err}"
        # 상류 오류는 200 으로도 온다
        if isinstance(data.get("error"), dict):
            err = data["error"]
            return None, f"HTTP {err.get('code')}: {err.get('message')}"
        if not data.get("choices"):
            return None, f"답에 choices 가 없음: {json.dumps(data, ensure_ascii=False)[:200]}"
        return data, ""

    @staticmethod
    def _retryable(detail: str) -> bool:
        """다시 물어볼 만한 실패인가. 429(한도)·5xx(상류 과부하)·끊김."""
        return any(code in detail for code in ("HTTP 429", "HTTP 500", "HTTP 502",
                                               "HTTP 503", "HTTP 504")) or "연결 실패" in detail

    def _formats(self, schema: dict[str, Any]) -> list[dict]:
        """응답 형식을 강한 것부터. 모델이 거절하면 한 칸씩 물러난다."""
        return [
            {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
            {"type": "json_schema", "json_schema": {"name": "answer", "strict": False, "schema": schema}},
            {"type": "json_object"},
        ]

    def _ask(self, base: dict, fmt: dict) -> tuple[dict | None, str]:
        """한 형식으로 묻는다. 한도·과부하는 여기서 몇 번 다시 물어본다."""
        body = dict(base, response_format=fmt)
        detail = ""
        for attempt in range(self.retries):
            if self.reasoning_locked:
                body.pop("reasoning", None)
            else:
                body["reasoning"] = {"enabled": False}
            data, detail = self._post(body)
            if data is not None:
                return data, ""
            if "Reasoning is mandatory" in detail:
                log.info("%s 는 사고를 끌 수 없습니다 — 켜고 다시 부릅니다", self.model)
                self.reasoning_locked = True
                continue
            if not self._retryable(detail):
                break
            wait = 5 * (attempt + 1) ** 2
            log.warning("OpenRouter %s — %d초 뒤 다시 (%d/%d)",
                        detail[:120], wait, attempt + 1, self.retries)
            time.sleep(wait)
        return None, detail

    @staticmethod
    def _format_problem(detail: str) -> bool:
        """모델이 응답 형식을 거절한 것인가 (그러면 한 칸 물러나 볼 만하다)."""
        low = detail.lower()
        return any(word in low for word in ("response_format", "json_schema", "schema",
                                            "structured output", "not support"))

    def _generate(self, system: str, user: str, schema: dict[str, Any],
                  max_tokens: int) -> Any | None:
        self.last_error = ""
        if not self.key:
            log.warning("%s 가 없습니다 — .env 에 OpenRouter 열쇠를 넣어 주세요.",
                        ENV_OPENROUTER_KEY)
            self.last_error = f"{ENV_OPENROUTER_KEY} 없음"
            return None
        base = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            # 추출은 창의성이 필요 없다. 0 이면 같은 이야기에 같은 답이 온다.
            "temperature": 0,
        }
        for fmt in self._formats(schema):
            data, detail = self._ask(base, fmt)
            if data is not None:
                return self._read(data)
            self.last_error = detail
            if not self._format_problem(detail):
                return None     # 형식 탓이 아니면 물러나도 소용없다
            log.info("응답 형식을 낮춰 다시 부릅니다: %s", detail[:120])
        return None

    def _read(self, data: dict) -> Any | None:
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            log.warning("답이 max_tokens 에서 잘렸습니다 — 상한을 올리거나 사고를 끄세요.")
        text = (choice.get("message") or {}).get("content") or ""
        return _extract_json(text)

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      max_tokens: int | None = None) -> dict | None:
        payload = self._generate(system, user, schema, max_tokens or 800)
        return payload if isinstance(payload, dict) else None

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        payload = self._generate(system, user, schema, 8000)
        return _coerce_relations(payload) or []


def build_backend(kind: str, model: str | None = None) -> Backend:
    if kind == "anthropic":
        return AnthropicBackend(model=model or "claude-opus-5")
    if kind == "mlx":
        return MLXBackend(model=model or DEFAULT_MLX_MODEL)
    if kind in ("ollama", "local"):
        return OllamaBackend(model=model or DEFAULT_LOCAL_MODEL)
    if kind in ("openrouter", "or"):
        return OpenRouterBackend(model=model)
    raise ValueError(f"알 수 없는 백엔드: {kind}")


def openrouter_ready() -> bool:
    """OpenRouter 열쇠가 있는가. 없으면 화면·CLI 가 로컬 모델로 간다."""
    return bool(os.environ.get(ENV_OPENROUTER_KEY, "").strip())


def default_life_backend() -> str:
    """개인 역사를 해석할 기본 백엔드.

    열쇠가 있으면 OpenRouter 다 — 이야기 하나에 한 번 부르는 일이라 무료
    한도(하루 1,000회) 안이고, MLX 처럼 35GB 를 잡지 않아 `extract` 가
    돌고 있어도 답한다. 열쇠가 없으면 예전처럼 로컬 MLX 로 간다."""
    return "openrouter" if openrouter_ready() else "mlx"
