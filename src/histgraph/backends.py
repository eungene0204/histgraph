"""추출 백엔드 — Claude API 또는 로컬 모델.

같은 프롬프트·스키마를 두 경로에 태운다. 로컬 모델은 API 키도 비용도
필요 없어서 971건 벌크 추출에 맞고, Claude 는 품질 기준선 역할을 한다.

**핵심 차이: 구조화 출력 강제 수준.**
  - Claude: `output_config.format` 이 스키마를 강제한다. 파싱은 항상 성공.
  - ollama 0.30.7: `format` 에 스키마 객체를 줘도 **무시된다**(실측 —
    자유 산문이 돌아왔다). `format: "json"` 문자열만 JSON 모드를 켠다.
    형태는 보장되지 않으므로 클라이언트에서 검증하고 고쳐 받아야 한다.

그래서 로컬 백엔드는 검증→재요청 루프를 갖는다. 이건 로컬 전용 우회가
아니라 방어로도 맞다 — 제약 디코딩이 걸려도 의미가 틀린 응답은 나온다.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Protocol

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_LOCAL_MODEL = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:Q5_K_M"


class Backend(Protocol):
    """추출 백엔드 공통 인터페이스."""

    name: str
    # 실제로 돌린 모델. 엣지에 이 값을 남긴다 — 어느 모델이 그 문장을
    # 판정했는지 모르면 나중에 틀린 엣지의 출처를 가릴 수 없다.
    model: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        """관계 목록을 돌려준다. 실패 시 빈 목록."""
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
        self._tokenizer = None

    def _build(self, schema: dict[str, Any]):
        """모델과 스키마 제약 생성기를 준비 (최초 1회)."""
        if self._generator is not None:
            return self._generator

        import outlines
        from mlx_lm import load
        from outlines.types import JsonSchema

        log.info("MLX 모델 로드 중: %s (최초 1회, 수십 초 소요)", self.model)
        model, tokenizer = load(self.model)
        self._tokenizer = tokenizer
        wrapped = outlines.from_mlxlm(model, tokenizer)
        self._generator = outlines.Generator(wrapped, JsonSchema(schema))
        log.info("MLX 모델 준비 완료")
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

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> list[dict]:
        generator = self._build(schema)
        prompt = self._chat_prompt(system, user)
        try:
            text = generator(prompt, max_tokens=self.max_tokens)
        except Exception as err:  # 생성 실패는 문서 하나만 건너뛴다
            log.warning("MLX 생성 실패: %s", err)
            return []

        payload = _extract_json(text)
        relations = _coerce_relations(payload)
        if relations is None:
            # 스키마가 강제되므로 여기 오면 대개 max_tokens 로 잘린 것이다
            log.warning("스키마 강제에도 파싱 실패 (잘림 의심): %s", text[-120:])
            return []
        return relations


def build_backend(kind: str, model: str | None = None) -> Backend:
    if kind == "anthropic":
        return AnthropicBackend(model=model or "claude-opus-5")
    if kind == "mlx":
        return MLXBackend(model=model or DEFAULT_MLX_MODEL)
    if kind in ("ollama", "local"):
        return OllamaBackend(model=model or DEFAULT_LOCAL_MODEL)
    raise ValueError(f"알 수 없는 백엔드: {kind}")
