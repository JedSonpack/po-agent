from s12_task_system.todo import TodoNag


def test_no_nag_below_threshold():
    nag = TodoNag()
    msgs = [{"role": "user", "content": "x"}]
    nag.on_round()
    nag.on_round()
    assert nag.maybe_nag(msgs) is None


def test_nag_at_threshold_and_resets():
    nag = TodoNag()
    msgs = [{"role": "user", "content": "x"}]
    nag.on_round(); nag.on_round(); nag.on_round()
    assert nag.maybe_nag(msgs) == "<reminder>Update your todos.</reminder>"
    assert nag.rounds_since_todo == 0


def test_no_nag_when_messages_empty():
    nag = TodoNag()
    nag.on_round(); nag.on_round(); nag.on_round()
    assert nag.maybe_nag([]) is None
    assert nag.rounds_since_todo == 3


def test_on_round_increments():
    nag = TodoNag()
    assert nag.rounds_since_todo == 0
    nag.on_round()
    assert nag.rounds_since_todo == 1


def test_on_todo_write_resets():
    nag = TodoNag()
    nag.on_round(); nag.on_round()
    nag.on_todo_write()
    assert nag.rounds_since_todo == 0


def test_custom_threshold_and_reminder():
    nag = TodoNag(threshold=2, reminder="nudge")
    msgs = [{"role": "user", "content": "x"}]
    nag.on_round(); nag.on_round()
    assert nag.maybe_nag(msgs) == "nudge"
