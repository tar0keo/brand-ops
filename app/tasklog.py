from connectors import store

_MEM = {}  # demo mode only


def recent(demo, days):
    """Return {task_key: ticket} for tasks ticketed within the cooldown window."""
    return dict(_MEM) if demo else store.tasklog_recent(days)


def record(demo, key, ticket):
    if demo:
        _MEM[key] = ticket
    else:
        store.tasklog_record(key, ticket)
