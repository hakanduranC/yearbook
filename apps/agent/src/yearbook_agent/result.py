"""The AgentResult contract (packages/openapi/openapi.yaml) as pydantic models.

Two layers: `PresentDraft` is what the model hands to `present` (ids only, discriminated on
`kind`); `AgentResult` is the wire shape the UI renders, with persons and albums hydrated from
tool results seen in the turn.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from . import ids

Locale = Literal["de", "en", "tr"]


class Chip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=500, description="The message sent when tapped")
    command_id: str | None = None


def _check_ids(v: list[str]) -> list[str]:
    bad = [x for x in v if not ids.is_id(x)]
    if bad:
        raise ValueError(f"not 22-character ids: {bad[:3]}")
    return v


# ---------------------------------------------------------------- what the model produces


class MediaDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["media"]
    title: str = Field(min_length=1, max_length=120)
    media_ids: list[str] = Field(max_length=500)
    group_by: Literal["time", "person", "none"] | None = None
    refine: list[Chip] = Field(default_factory=list, max_length=6)

    _ids = field_validator("media_ids")(_check_ids)


class PeopleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["people"]
    title: str = Field(min_length=1, max_length=120)
    person_ids: list[str] = Field(max_length=200)

    _ids = field_validator("person_ids")(_check_ids)


class StatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["stat"]
    title: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=80)
    detail: str | None = Field(default=None, max_length=300)
    media_ids: list[str] = Field(default_factory=list, max_length=200)

    _ids = field_validator("media_ids")(_check_ids)


class AlbumDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["album"]
    album_id: str
    title: str | None = Field(default=None, max_length=120)

    @field_validator("album_id")
    @classmethod
    def _album(cls, v: str) -> str:
        if not ids.is_id(v):
            raise ValueError("album_id must be the 22-character id returned by create_album")
        return v


class ClarifyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["clarify"]
    question: str = Field(min_length=1, max_length=200)
    options: list[str] = Field(min_length=2, max_length=5)


class EmptyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["empty"]
    title: str = Field(min_length=1, max_length=160)
    suggestions: list[Chip] = Field(default_factory=list, max_length=6)


PresentDraft = Annotated[
    MediaDraft | PeopleDraft | StatDraft | AlbumDraft | ClarifyDraft | EmptyDraft,
    Field(discriminator="kind"),
]
_draft_adapter: TypeAdapter[Any] = TypeAdapter(PresentDraft)


class PresentCall(BaseModel):
    """Arguments of the `present` tool: a one-line `understood` plus the result."""

    model_config = ConfigDict(extra="forbid")
    understood: str = Field(min_length=1, max_length=200)
    result: PresentDraft


def validate_present(args: dict[str, Any]) -> PresentCall:
    """Raises pydantic.ValidationError with messages the model can act on."""
    return PresentCall.model_validate(args)


def format_validation_error(err: ValidationError) -> str:
    lines = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        lines.append(f"{loc}: {e['msg']}")
    return "present rejected: " + "; ".join(lines[:6])


# ---------------------------------------------------------------- wire shapes


class Person(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    event_slug: str = ""
    display_name: str | None = None
    named: bool = False
    face_count: int = 0
    is_me: bool = False
    hidden: bool = False


class Album(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    event_slug: str | None = None
    title: str
    kind: Literal["highlights", "manual", "agent"] = "agent"
    count: int = 0


class MediaResult(BaseModel):
    kind: Literal["media"] = "media"
    title: str
    media_ids: list[str]
    group_by: Literal["time", "person", "none"] | None = None


class PeopleResult(BaseModel):
    kind: Literal["people"] = "people"
    title: str
    persons: list[Person]
    person_ids: list[str]


class StatResult(BaseModel):
    kind: Literal["stat"] = "stat"
    title: str
    value: str
    detail: str | None = None
    media_ids: list[str] = Field(default_factory=list)


class AlbumResult(BaseModel):
    kind: Literal["album"] = "album"
    album: Album


class ClarifyResult(BaseModel):
    kind: Literal["clarify"] = "clarify"
    question: str
    options: list[str]


class EmptyResult(BaseModel):
    kind: Literal["empty"] = "empty"
    title: str


AgentResult = Annotated[
    MediaResult | PeopleResult | StatResult | AlbumResult | ClarifyResult | EmptyResult,
    Field(discriminator="kind"),
]


class Attachment(BaseModel):
    name: str
    url: str
    mime: str
    width: int | None = None
    height: int | None = None


class AgentResponse(BaseModel):
    conversation_id: str
    turn_id: str
    understood: str
    result: AgentResult
    suggestions: list[Chip]
    saveable: bool
    attachments: list[Attachment] = Field(default_factory=list)


class SavedCommand(BaseModel):
    id: str
    name: str
    label: str
    description: str
    scope: Literal["event", "global"]
    event_slug: str | None = None
    params: dict[str, Any]
    shared: bool = False
    kind: Literal["sql", "search", "python"] = "sql"
    created_by_agent: bool = False
    run_count: int = 0


def to_wire(draft: PresentCall, entities: dict[str, Any]) -> tuple[Any, list[Chip]]:
    """Turn the model's draft into the contract shape plus the suggestion chips.

    `entities` is what the turn saw in tool results:
    {"persons": {id: {...}}, "albums": {id: {...}}}.
    """
    r = draft.result
    persons_seen: dict[str, Any] = entities.get("persons", {})
    albums_seen: dict[str, Any] = entities.get("albums", {})
    match r:
        case MediaDraft():
            return MediaResult(title=r.title, media_ids=r.media_ids, group_by=r.group_by), r.refine
        case PeopleDraft():
            persons = [
                Person.model_validate({**persons_seen.get(pid, {}), "id": pid})
                for pid in r.person_ids
            ]
            return PeopleResult(title=r.title, persons=persons, person_ids=r.person_ids), []
        case StatDraft():
            return StatResult(
                title=r.title, value=r.value, detail=r.detail, media_ids=r.media_ids
            ), []
        case AlbumDraft():
            seen = albums_seen.get(r.album_id, {})
            album = Album.model_validate(
                {**seen, "id": r.album_id, "title": r.title or seen.get("title") or "Album"}
            )
            return AlbumResult(album=album), []
        case ClarifyDraft():
            return ClarifyResult(question=r.question, options=r.options), []
        case EmptyDraft():
            return EmptyResult(title=r.title), r.suggestions
    raise TypeError(type(r))  # pragma: no cover
