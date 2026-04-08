from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Card:
    title: str
    description: str = ""


class TaskBoard:
    def __init__(self) -> None:
        self._cards: list[Card] = []

    def create_card(self, title: str, description: str = "") -> Card:
        trimmed_title = title.strip()
        if not trimmed_title:
            raise ValueError("title is required")
        card = Card(title=trimmed_title, description=description.strip())
        self._cards.append(card)
        return card

    def list_cards(self) -> list[Card]:
        return list(self._cards)
