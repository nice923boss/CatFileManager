"""Undo stack: move back, rename back, restore from the recycle bin."""

from send2trash import send2trash

from undo import UndoStack, trash_records


def test_undo_move_and_rename(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "sub" / "b.txt"
    b.parent.mkdir()
    b.write_text("x")
    stack = UndoStack()
    stack.push("移動 a.txt", [("moved", str(a), str(b))])
    assert stack.peek_label() == "移動 a.txt"
    label, errors = stack.undo()
    assert not errors and a.read_text() == "x" and not b.exists()
    assert stack.undo() is None


def test_undo_refuses_to_clobber(tmp_path):
    (tmp_path / "old.txt").write_text("someone else")
    (tmp_path / "new.txt").write_text("mine")
    stack = UndoStack()
    stack.push("重新命名", [("renamed", str(tmp_path / "old.txt"), str(tmp_path / "new.txt"))])
    _, errors = stack.undo()
    assert errors and (tmp_path / "old.txt").read_text() == "someone else"


def test_restore_from_recycle_bin(tmp_path):
    f = tmp_path / "trash_me.txt"
    f.write_text("come back")
    records = trash_records([str(f)])
    send2trash(str(f))
    assert not f.exists()
    stack = UndoStack()
    stack.push("刪除", records)
    _, errors = stack.undo()
    assert not errors
    assert f.read_text() == "come back"
