from dataclasses import dataclass
from typing import Literal


ContentType = Literal["article", "tweet"]


@dataclass(frozen=True, slots=True)
class ParsedXPage:
    title: str
    markdown: str
    content_type: ContentType

