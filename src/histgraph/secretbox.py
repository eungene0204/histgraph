"""내 역사를 **봉투에 넣어** 저장한다 — 표에 드는 것은 읽을 수 없는 글자다.

## 무엇을 막는가

계정에 담아 둔 내 역사(`life_docs.doc`)는 여태 평문 JSON 이었다. 세션으로
문은 잠겨 있었지만(`auth.life_doc` 은 `user_id` 로만 찾는다), **표를 통째로
떠 가는 길**은 문을 지나지 않는다 — 데이터베이스 덤프, 내려받은 백업,
연결 문자열이 새는 경우. 봉투는 그 길을 막는다. 2026-09-11 사용자 결정.

**막지 못하는 것도 적어 둔다.** 서버가 통째로 뚫려 열쇠까지 함께 털리면
소용이 없다 (열쇠가 그 서버의 환경변수에 있다). 브라우저에 남는 사본과
모델에게 보내는 순간도 평문이다 — 앞의 것은 주인 표가 지키고(`lifestore.js`),
뒤의 것은 방침 제4조가 밝힌다.

## 봉투란

문서마다 **일회용 열쇠(DEK)** 를 새로 뽑아 그것으로 문서를 잠그고, 그
열쇠를 다시 **큰 열쇠(KEK, `HISTGRAPH_DATA_KEY`)** 로 잠가 함께 담는다.
큰 열쇠를 갈 때 문서를 전부 다시 잠글 필요 없이 **작은 열쇠만 다시 싸면**
된다. 담기는 모양은 문서가 있던 그 자리다 (표를 고치지 않는다):

    {"enc": "histgraph-v1", "kid": "3f2a…", "key": "…", "doc": "…"}

`kid` 는 어느 큰 열쇠로 잠갔는지다. 열쇠를 갈면 옛 것을 `HISTGRAPH_DATA_KEY_OLD`
에 두어 **읽기는 계속되게** 하고, 다시 쓸 때 새 열쇠로 바뀐다.

## 왜 AES 가 아닌가

이 저장소의 본체는 **표준 라이브러리만으로 돈다** (`pyproject.toml` —
`dependencies = []`). 배포는 그 규칙 위에 서 있어서 서버리스 함수에
`requirements.txt` 조차 없다. 파이썬 표준 라이브러리에는 AES 가 없다.

그래서 표준 라이브러리가 주는 것(HMAC-SHA256)으로 짓는다:

- **잠그기** — 열쇠줄기를 `HMAC-SHA256(enc_key, nonce ‖ i)` 로 뽑아 xor 한다
  (NIST SP 800-108 의 계수 모드 KDF 와 같은 꼴이다. HMAC 은 의사난수함수라
  뽑히는 줄기가 열쇠를 모르면 난수와 구별되지 않는다).
- **봉인** — `HMAC-SHA256(mac_key, 꼬리표 ‖ nonce ‖ 암호문)` 을 뒤에 붙이고,
  풀 때 **먼저 이것부터 본다** (encrypt-then-MAC). 한 글자라도 손대면 열지
  않는다. 견주는 것은 상수 시간(`hmac.compare_digest`)이다.
- 두 열쇠(`enc`·`mac`)는 한 열쇠에서 갈라 쓴다 — 같은 열쇠로 두 일을 하지 않는다.
- nonce 는 문서마다 새로 뽑는 16바이트다 (`secrets`). 같은 문서를 두 번
  저장해도 표에 드는 글자가 다르다.

의존성을 하나 들일 수 있으면 AES-GCM 이 낫다. 그때 갈아 끼우는 자리는
`_lock`·`_unlock` 둘이고, `enc` 의 이름표를 올려 옛 봉투도 계속 열면 된다.

## 열쇠가 없으면

평문으로 둔다 — 열쇠 없는 컴퓨터에서 내 역사를 아예 못 쓰게 만들지 않는다
(로컬 개발). 대신 **배포에서는 소리 내어 적는다.** 열쇠는
`uv run histgraph datakey` 가 만들고, 그 명령이 지금 어디가 잠겨 있는지도 센다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets

log = logging.getLogger(__name__)

ENV_KEY = "HISTGRAPH_DATA_KEY"
ENV_OLD = "HISTGRAPH_DATA_KEY_OLD"      # 열쇠를 가는 동안 옛 봉투를 읽는 자리

FORMAT = "histgraph-v1"                 # 봉투의 이름표. 모양을 바꾸면 올린다.
TAG = b"histgraph-life-v1"              # 봉인에 함께 넣는 꼬리표 (쓰임을 못 바꾸게)
NONCE = 16
KEY_BYTES = 32


class SecretError(Exception):
    """봉투를 여닫지 못했다. 사람에게 보여도 되는 한국어 문장."""


# --- 열쇠 -------------------------------------------------------------------


def new_key() -> str:
    """새 큰 열쇠 한 벌. `.env` 와 배포 환경변수에 **같은 값**을 둔다."""
    return _b64(secrets.token_bytes(KEY_BYTES))


def _material(text: str) -> bytes | None:
    """환경변수에 든 글자를 열쇠로. 짧으면 열쇠가 아니다."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        got = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(got) >= KEY_BYTES:
            return hashlib.sha256(got).digest()
    except (ValueError, base64.binascii.Error):
        pass
    if len(raw) >= KEY_BYTES:               # base64 가 아니어도 긴 글자면 받는다
        return hashlib.sha256(raw.encode("utf-8")).digest()
    raise SecretError(f"{ENV_KEY} 가 너무 짧습니다 — `histgraph datakey` 로 만드세요.")


def _keys() -> list[bytes]:
    """읽을 때 쓸 열쇠들. 첫째가 지금 쓰는 것이고 나머지는 옛 것이다."""
    out = []
    for name in (ENV_KEY, ENV_OLD):
        got = _material(os.environ.get(name, ""))
        if got:
            out.append(got)
    return out


def enabled() -> bool:
    """지금 잠글 수 있는가."""
    try:
        return bool(_material(os.environ.get(ENV_KEY, "")))
    except SecretError:
        return False


def key_id(key: bytes) -> str:
    """어느 열쇠로 잠갔는지 적어 두는 짧은 이름. 열쇠 자체는 새지 않는다."""
    return hashlib.sha256(b"kid:" + key).hexdigest()[:12]


def current_id() -> str:
    keys = _keys()
    return key_id(keys[0]) if keys else ""


# --- 잠그고 풀기 -------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    """한 열쇠에서 잠그는 열쇠와 봉인하는 열쇠를 갈라 낸다."""
    return (hmac.new(key, b"seal-enc", hashlib.sha256).digest(),
            hmac.new(key, b"seal-mac", hashlib.sha256).digest())


def _stream(enc_key: bytes, nonce: bytes, size: int) -> bytes:
    """열쇠줄기 (계수 모드). 32바이트씩 이어 붙인다."""
    out = bytearray()
    block = 0
    while len(out) < size:
        out += hmac.new(enc_key, nonce + block.to_bytes(4, "big"), hashlib.sha256).digest()
        block += 1
    return bytes(out[:size])


def _lock(key: bytes, raw: bytes) -> str:
    """`nonce ‖ 암호문 ‖ 봉인` 을 한 글자줄로."""
    enc_key, mac_key = _subkeys(key)
    nonce = secrets.token_bytes(NONCE)
    stream = _stream(enc_key, nonce, len(raw))
    body = bytes(a ^ b for a, b in zip(raw, stream))
    seal = hmac.new(mac_key, TAG + nonce + body, hashlib.sha256).digest()
    return _b64(nonce + body + seal)


def _unlock(key: bytes, blob: str) -> bytes:
    """봉인부터 본다. 맞지 않으면 **아무것도 돌려주지 않는다.**"""
    try:
        raw = _unb64(blob)
    except (ValueError, base64.binascii.Error):
        raise SecretError("봉투가 깨져 있습니다.") from None
    if len(raw) < NONCE + 32:
        raise SecretError("봉투가 깨져 있습니다.")
    nonce, body, seal = raw[:NONCE], raw[NONCE:-32], raw[-32:]
    enc_key, mac_key = _subkeys(key)
    want = hmac.new(mac_key, TAG + nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(want, seal):
        raise SecretError("봉인이 맞지 않습니다.")
    return bytes(a ^ b for a, b in zip(body, _stream(enc_key, nonce, len(body))))


# --- 문서 -------------------------------------------------------------------


def sealed(doc: object) -> bool:
    """이미 봉투에 든 것인가."""
    return isinstance(doc, dict) and doc.get("enc") == FORMAT


def seal(doc: dict) -> dict:
    """문서를 봉투에 넣는다. **열쇠가 없으면 그대로 돌려준다** (평문).

    돌려주는 것은 그대로 `life_docs.doc` 에 드는 JSON 이다."""
    if sealed(doc):
        return doc
    keys = _keys()
    if not keys:
        if os.environ.get("VERCEL"):
            log.warning("%s 가 없어 내 역사를 평문으로 담습니다.", ENV_KEY)
        return doc
    kek = keys[0]
    dek = secrets.token_bytes(KEY_BYTES)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    return {"enc": FORMAT, "kid": key_id(kek),
            "key": _lock(kek, dek), "doc": _lock(dek, raw)}


def unseal(doc: object) -> dict:
    """봉투면 열고, 평문이면 그대로. 못 열면 `SecretError`.

    **못 열 때 빈 문서를 돌려주지 않는다** — 그러면 화면이 '자료가 없다'로
    읽고, 다음 저장이 그 빈 것을 덮어써 삶이 사라진다."""
    if not sealed(doc):
        if isinstance(doc, dict):
            return doc
        raise SecretError("문서가 아닙니다.")
    keys = _keys()
    if not keys:
        raise SecretError(f"{ENV_KEY} 가 없어 담아 둔 내 역사를 열지 못했습니다.")
    kid = doc.get("kid") or ""
    order = [k for k in keys if key_id(k) == kid] or keys
    last = None
    for kek in order:
        try:
            dek = _unlock(kek, str(doc.get("key") or ""))
            return json.loads(_unlock(dek, str(doc.get("doc") or "")).decode("utf-8"))
        except (SecretError, ValueError, UnicodeDecodeError) as err:
            last = err
    raise SecretError(
        "담아 둔 내 역사를 열지 못했습니다 — 열쇠가 바뀌었으면 "
        f"{ENV_OLD} 에 옛 열쇠를 넣어 주세요." if last else "봉투를 열지 못했습니다.")


def reseal(store, table: str = "life_docs") -> tuple[int, int]:
    """표에 남은 평문·옛 열쇠 봉투를 **지금 열쇠로** 다시 잠근다.

    돌려주는 것은 (다시 잠근 수, 그대로 둔 수). 열쇠가 없으면 아무것도 안 한다.
    `histgraph datakey --seal` 이 부른다."""
    if not enabled():
        raise SecretError(f"{ENV_KEY} 가 없습니다 — `histgraph datakey` 로 만드세요.")
    now = current_id()
    done = kept = 0
    for row in store.query(f"select user_id, doc from {table}", []):
        doc = row["doc"]
        if isinstance(doc, str):
            doc = json.loads(doc)
        if sealed(doc) and doc.get("kid") == now:
            kept += 1
            continue
        plain = unseal(doc)             # 못 열면 여기서 멈춘다 (덮어쓰지 않는다)
        store.query(
            f"update {table} set doc = $1::jsonb where user_id = $2",
            [json.dumps(seal(plain), ensure_ascii=False), row["user_id"]])
        done += 1
    return done, kept
