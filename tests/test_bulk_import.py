"""Bulk import parsing: the paste format is strict on purpose."""

from butter.core.bulk_import import parse_bulk

GOOD = "inbox@example.com----account-password----US 主号"


def test_parses_a_well_formed_line():
    result = parse_bulk(GOOD)
    assert result.ok
    assert len(result.accounts) == 1
    account = result.accounts[0]
    assert account.email == "inbox@example.com"
    assert account.password == "account-password"
    assert account.note == "US 主号"


def test_note_may_be_empty():
    result = parse_bulk("inbox@example.com----account-password----")
    assert result.ok
    assert result.accounts[0].note == ""


def test_blank_lines_and_comments_are_skipped():
    result = parse_bulk(f"\n\n# 注释\n{GOOD}\n\n")
    assert result.ok
    assert len(result.accounts) == 1


def test_two_fields_is_rejected():
    result = parse_bulk("a@b.co----pw")
    assert not result.ok
    assert "3 段" in result.errors[0].reason


def test_bad_email_is_rejected():
    result = parse_bulk("not-an-email----pw----备注")
    assert not result.ok
    assert "邮箱" in result.errors[0].reason


def test_empty_password_is_rejected():
    result = parse_bulk("a@b.co--------备注")
    assert not result.ok
    assert "密码" in result.errors[0].reason


def test_duplicate_in_paste_is_rejected():
    result = parse_bulk(f"{GOOD}\n{GOOD}")
    assert not result.ok
    assert "重复" in result.errors[0].reason


def test_every_bad_line_is_reported():
    result = parse_bulk("\n".join([GOOD, "a@b.co----pw", "x----pw----备注"]))
    assert len(result.accounts) == 1
    assert len(result.errors) == 2
