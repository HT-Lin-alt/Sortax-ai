from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ManifestDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    accessed_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,199}$")
    title: str = Field(min_length=1)
    source_url: HttpUrl
    local_path: Path
    media_type: str
    claim_type: str = Field(min_length=1)

    @field_validator("source_url")
    @classmethod
    def source_must_be_official_ato(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.host != "www.ato.gov.au":
            raise ValueError("source URL must use HTTPS on the official www.ato.gov.au host")
        return value

    @field_validator("local_path")
    @classmethod
    def local_path_must_be_relative(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("local path must be relative and cannot traverse parents")
        return value

    @field_validator("media_type")
    @classmethod
    def media_type_must_be_supported(cls, value: str) -> str:
        supported = {"text/html", "application/pdf", "text/plain", "text/markdown"}
        if value not in supported:
            raise ValueError("unsupported knowledge source media type")
        return value


class KnowledgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    collection: str = Field(min_length=1)
    defaults: ManifestDefaults
    sources: list[KnowledgeSource] = Field(min_length=1)

    @field_validator("sources")
    @classmethod
    def document_ids_must_be_unique(cls, value: list[KnowledgeSource]) -> list[KnowledgeSource]:
        document_ids = [source.document_id for source in value]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("manifest document IDs must be unique")
        return value
