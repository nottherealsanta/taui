from __future__ import annotations

import pytest

from example_project.src.task_board import TaskBoard


def test_create_card_trims_and_persists() -> None:
    board = TaskBoard()

    card = board.create_card("  Write docs  ", "  Add usage example  ")

    assert card.title == "Write docs"
    assert card.description == "Add usage example"
    assert board.list_cards() == [card]


def test_create_card_requires_title() -> None:
    board = TaskBoard()

    with pytest.raises(ValueError, match="title is required"):
        board.create_card("   ")
