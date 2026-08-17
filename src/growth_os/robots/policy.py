import re
from dataclasses import dataclass
from enum import StrEnum

_MAX_ROBOTS_BYTES = 512_000
_PRODUCT_TOKEN = "GrowthOSBot"
_PRODUCT_TOKEN_PATTERN = re.compile(r"(?:[A-Za-z_-]+|\*)\Z")
_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class RobotsPolicyErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    TOO_LARGE = "too_large"
    INVALID_ENCODING = "invalid_encoding"


class RobotsPolicyError(ValueError):
    code: RobotsPolicyErrorCode

    def __init__(self, code: RobotsPolicyErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class RobotsDecisionReason(StrEnum):
    ROBOTS_URI = "robots_uri"
    MATCHED_ALLOW = "matched_allow"
    MATCHED_DISALLOW = "matched_disallow"
    NO_MATCHING_GROUP = "no_matching_group"
    NO_MATCHING_RULE = "no_matching_rule"


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    allowed: bool
    reason: RobotsDecisionReason
    matched_user_agent: str | None
    matched_rule: str | None


@dataclass(frozen=True, slots=True)
class _Rule:
    allowed: bool
    normalized: str
    tokens: tuple[int | None, ...]
    anchored: bool
    specificity: int


@dataclass(slots=True)
class _Group:
    agents: list[str]
    rules: list[_Rule]


def _invalid_input() -> RobotsPolicyError:
    return RobotsPolicyError(RobotsPolicyErrorCode.INVALID_INPUT, "Invalid robots policy input.")


def _validate_target(target_path: str) -> None:
    if (
        type(target_path) is not str
        or not target_path.startswith("/")
        or target_path.startswith("//")
        or "#" in target_path
    ):
        raise _invalid_input()
    for index, character in enumerate(target_path):
        codepoint = ord(character)
        if codepoint < 0x20 or codepoint == 0x7F or 0xD800 <= codepoint <= 0xDFFF:
            raise _invalid_input()
        if character == "%" and (
            index + 2 >= len(target_path)
            or target_path[index + 1] not in _HEX_DIGITS
            or target_path[index + 2] not in _HEX_DIGITS
        ):
            raise _invalid_input()


def _normalize(value: str, *, pattern: bool) -> tuple[str, tuple[int | None, ...]]:
    normalized: list[str] = []
    tokens: list[int | None] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "%":
            if (
                index + 2 >= len(value)
                or value[index + 1] not in _HEX_DIGITS
                or value[index + 2] not in _HEX_DIGITS
            ):
                raise ValueError
            octet = int(value[index + 1 : index + 3], 16)
            if octet in _UNRESERVED:
                normalized.append(chr(octet))
                tokens.append(octet)
            else:
                normalized.append(f"%{octet:02X}")
                tokens.append(256 + octet)
            index += 3
            continue
        if pattern and character == "*":
            normalized.append(character)
            tokens.append(None)
        elif ord(character) < 0x80:
            normalized.append(character)
            tokens.append(ord(character))
        else:
            for octet in character.encode("utf-8"):
                normalized.append(f"%{octet:02X}")
                tokens.append(256 + octet)
        index += 1
    return "".join(normalized), tuple(tokens)


def _parse_rule(value: str, *, allowed: bool) -> _Rule | None:
    if not value or not value.startswith("/"):
        return None
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        return None
    try:
        normalized, tokens = _normalize(value, pattern=True)
    except ValueError:
        return None
    anchored = normalized.endswith("$")
    if anchored:
        tokens = tokens[:-1]
    specificity = sum(token is not None for token in tokens)
    return _Rule(allowed, normalized, tokens, anchored, specificity)


def _parse_groups(robots_text: str) -> list[_Group]:
    groups: list[_Group] = []
    current: _Group | None = None
    for raw_line in re.split(r"\r\n|\r|\n", robots_text):
        line = raw_line.split("#", 1)[0]
        if ":" not in line:
            continue
        raw_field, raw_value = line.split(":", 1)
        field = raw_field.strip(" \t").lower()
        value = raw_value.strip(" \t")
        if field == "user-agent":
            if _PRODUCT_TOKEN_PATTERN.fullmatch(value) is None:
                continue
            if current is None or current.rules:
                current = _Group([], [])
                groups.append(current)
            current.agents.append(value)
            continue
        if field not in {"allow", "disallow"} or current is None:
            continue
        rule = _parse_rule(value, allowed=field == "allow")
        if rule is not None:
            current.rules.append(rule)
    return groups


def _matches(rule: _Rule, target: tuple[int | None, ...]) -> bool:
    pattern = rule.tokens if rule.anchored else (*rule.tokens, None)
    pattern_index = 0
    target_index = 0
    star_index = -1
    star_target_index = -1
    while target_index < len(target):
        if pattern_index < len(pattern) and pattern[pattern_index] == target[target_index]:
            pattern_index += 1
            target_index += 1
        elif pattern_index < len(pattern) and pattern[pattern_index] is None:
            star_index = pattern_index
            star_target_index = target_index
            pattern_index += 1
        elif star_index >= 0:
            star_target_index += 1
            target_index = star_target_index
            pattern_index = star_index + 1
        else:
            return False
    while pattern_index < len(pattern) and pattern[pattern_index] is None:
        pattern_index += 1
    return pattern_index == len(pattern)


def evaluate_robots(*, robots_txt: bytes, target_path: str) -> RobotsDecision:
    if type(robots_txt) is not bytes or type(target_path) is not str:
        raise _invalid_input()
    if len(robots_txt) > _MAX_ROBOTS_BYTES:
        raise RobotsPolicyError(RobotsPolicyErrorCode.TOO_LARGE, "Robots.txt is too large.")
    try:
        robots_text = robots_txt.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise RobotsPolicyError(
            RobotsPolicyErrorCode.INVALID_ENCODING, "Invalid robots.txt encoding."
        ) from None
    _validate_target(target_path)
    normalized_target, target_tokens = _normalize(target_path, pattern=False)
    target_uri = normalized_target.split("?", 1)[0]
    if target_uri == "/robots.txt":
        return RobotsDecision(True, RobotsDecisionReason.ROBOTS_URI, None, None)

    groups = _parse_groups(robots_text)
    exact_groups = [
        group
        for group in groups
        if any(agent.lower() == _PRODUCT_TOKEN.lower() for agent in group.agents)
    ]
    selected_groups = exact_groups or [group for group in groups if "*" in group.agents]
    if not selected_groups:
        return RobotsDecision(True, RobotsDecisionReason.NO_MATCHING_GROUP, None, None)

    matched_agent = _PRODUCT_TOKEN if exact_groups else "*"
    unique_rules = dict.fromkeys(rule for group in selected_groups for rule in group.rules)
    winner: _Rule | None = None
    for rule in unique_rules:
        if not _matches(rule, target_tokens):
            continue
        if winner is None or rule.specificity > winner.specificity:
            winner = rule
        elif rule.specificity == winner.specificity and rule.allowed and not winner.allowed:
            winner = rule
    if winner is None:
        return RobotsDecision(True, RobotsDecisionReason.NO_MATCHING_RULE, matched_agent, None)
    reason = (
        RobotsDecisionReason.MATCHED_ALLOW
        if winner.allowed
        else RobotsDecisionReason.MATCHED_DISALLOW
    )
    return RobotsDecision(winner.allowed, reason, matched_agent, winner.normalized)


__all__ = [
    "RobotsDecision",
    "RobotsDecisionReason",
    "RobotsPolicyError",
    "RobotsPolicyErrorCode",
    "evaluate_robots",
]
