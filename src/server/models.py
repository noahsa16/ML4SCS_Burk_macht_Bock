from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class SessionStartBody(BaseModel):
    person_id: str = "unknown"
    description: str = ""
    force_preflight: bool = False

    @field_validator("person_id", mode="before")
    @classmethod
    def normalize_person_id(cls, v: object) -> str:
        s = str(v).strip() if v is not None else ""
        return s or "unknown"

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: object) -> str:
        return str(v).strip() if v is not None else ""


class StudyStartBody(BaseModel):
    protocol_id: str = "v2"
    person_id: str = "unknown"
    description: str = ""
    force_preflight: bool = False
    test_mode: bool = False

    @field_validator("person_id", mode="before")
    @classmethod
    def normalize_person_id(cls, v: object) -> str:
        s = str(v).strip() if v is not None else ""
        return s or "unknown"

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: object) -> str:
        return str(v).strip() if v is not None else ""


class WatchSample(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ts: Optional[int] = None
    ax: Optional[float] = None
    ay: Optional[float] = None
    az: Optional[float] = None
    rx: Optional[float] = None
    ry: Optional[float] = None
    rz: Optional[float] = None
    # Modern-Pool ab 2026-05-26. Optional[float] = None macht das Feld
    # rückwärts-kompatibel: Payloads von Pre-Modern-Watch-Clients (ohne
    # gravity capture) lassen die Felder einfach weg, Pydantic füllt None.
    gx: Optional[float] = None
    gy: Optional[float] = None
    gz: Optional[float] = None


class WatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    samples:          list[WatchSample] = []
    sequence:         Optional[int]   = None
    sampleRateHz:     Optional[float] = None
    watchSentAt:      Optional[int]   = None
    phoneReceivedAt:  Optional[int]   = None
    source:           Optional[str]   = None
    sessionId:        Optional[str]   = None

    @model_validator(mode="before")
    @classmethod
    def accept_list_format(cls, v: object) -> object:
        """Allow a bare list of samples as the entire payload."""
        if isinstance(v, list):
            return {"samples": v}
        return v

    @field_validator("samples", mode="before")
    @classmethod
    def drop_non_dict_samples(cls, v: object) -> list:
        """Silently discard any sample that isn't a dict so one bad entry
        doesn't reject the whole batch."""
        if not isinstance(v, list):
            return []
        return [s for s in v if isinstance(s, dict)]


class AirPodsSample(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ts: Optional[int] = None
    ax: Optional[float] = None
    ay: Optional[float] = None
    az: Optional[float] = None
    rx: Optional[float] = None
    ry: Optional[float] = None
    rz: Optional[float] = None
    qw: Optional[float] = None
    qx: Optional[float] = None
    qy: Optional[float] = None
    qz: Optional[float] = None
    gx: Optional[float] = None
    gy: Optional[float] = None
    gz: Optional[float] = None


class AirPodsEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    samples:          list[AirPodsSample] = []
    sequence:         Optional[int]   = None
    sampleRateHz:     Optional[float] = None
    airpodsSentAt:    Optional[int]   = None
    phoneReceivedAt:  Optional[int]   = None
    source:           Optional[str]   = None
    sessionId:        Optional[str]   = None

    @model_validator(mode="before")
    @classmethod
    def accept_list_format(cls, v: object) -> object:
        if isinstance(v, list):
            return {"samples": v}
        return v

    @field_validator("samples", mode="before")
    @classmethod
    def drop_non_dict_samples(cls, v: object) -> list:
        if not isinstance(v, list):
            return []
        return [s for s in v if isinstance(s, dict)]
