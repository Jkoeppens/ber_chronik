"""
chat.py — die Frage an ein Projekt

Nur der Rumpf. Die Antwort ist ein Ereignisstrom (text/event-stream) und hat
deshalb kein Antwortmodell — was darin vorkommt, steht im Doktext der Route
und in src/neu/chat/dienst.py.
"""

from pydantic import BaseModel, Field


class ChatRumpf(BaseModel):
    """Eine Frage auf Deutsch."""

    frage: str = Field(
        min_length=1,
        description="Die Frage. Leer wird abgewiesen, nicht stumm beantwortet.",
    )
