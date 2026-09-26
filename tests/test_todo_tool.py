import re
import pytest
from application.agents.tools.todo_list import TodoListTool
from application.core.settings import settings


class FakeCursor(list):
    def sort(self, key, direction):
        reverse = direction == -1
        sorted_list = sorted(self, key=lambda d: d.get(key, 0), reverse=reverse)
        return FakeCursor(sorted_list)

    def limit(self, count):
        return FakeCursor(self[:count])

    def __iter__(self):
        return self

    def __next__(self):
        if not self:
            raise StopIteration
        return self.pop(0)


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def create_index(self, *args, **kwargs):
        pass

    def insert_one(self, doc):
        key = (doc["user_id"], doc["tool_id"], int(doc["todo_id"]))
        self.docs[key] = doc
        return type("res", (), {"inserted_id": key})

    def find_one(self, query):
        key = (query.get("user_id"), query.get("tool_id"), int(query.get("todo_id")))
        return self.docs.get(key)

    def find(self, query):
        user_id = query.get("user_id")
        tool_id = query.get("tool_id")
        filtered = [
            doc for (uid, tid, _), doc in self.docs.items()
            if uid == user_id and tid == tool_id
        ]
        return FakeCursor(filtered)

    def update_one(self, query, update, upsert=False):
        key = (query.get("user_id"), query.get("tool_id"), int(query.get("todo_id")))
        if key in self.docs:
            self.docs[key].update(update.get("$set", {}))
            return type("res", (), {"matched_count": 1})
        elif upsert:
            new_doc = {**query, **update.get("$set", {})}
            self.docs[key] = new_doc
            return type("res", (), {"matched_count": 1})
        else:
            return type("res", (), {"matched_count": 0})

    def delete_one(self, query):
        key = (query.get("user_id"), query.get("tool_id"), int(query.get("todo_id")))
        if key in self.docs:
            del self.docs[key]
            return type("res", (), {"deleted_count": 1})
        return type("res", (), {"deleted_count": 0})


@pytest.fixture
def todo_tool(monkeypatch) -> TodoListTool:
    """Provides a TodoListTool with a fake MongoDB backend."""
    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)
    return TodoListTool({"tool_id": "test_tool"}, user_id="test_user")


def _extract_todo_id(create_result: str) -> int:
    """Extract the todo ID from a create result string like 'Todo created with ID 1: Title'."""
    match = re.search(r'Todo created with ID (\d+)', create_result)
    if match:
        return int(match.group(1))
    raise ValueError(f"Cannot extract todo_id from: {create_result}")


def test_create_and_get(todo_tool: TodoListTool):
    res = todo_tool.execute_action("create", title="Write tests")
    assert "Todo created with ID" in res
    assert "Write tests" in res
    todo_id = _extract_todo_id(res)

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert f"Todo [{todo_id}]" in get_res
    assert "Write tests" in get_res
    assert "open" in get_res


def test_get_all_todos(todo_tool: TodoListTool):
    todo_tool.execute_action("create", title="Task 1")
    todo_tool.execute_action("create", title="Task 2")

    list_res = todo_tool.execute_action("list")
    assert "Todos:" in list_res
    assert "[1] Task 1 (open)" in list_res
    assert "[2] Task 2 (open)" in list_res


def test_update_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("create", title="Initial Title")
    todo_id = _extract_todo_id(create_res)

    update_res = todo_tool.execute_action("update", todo_id=todo_id, title="Updated Title")
    assert "updated to: Updated Title" in update_res

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "Updated Title" in get_res
    # status remains "open" because _update only changes title
    assert "open" in get_res


def test_delete_todo(todo_tool: TodoListTool):
    create_res = todo_tool.execute_action("create", title="To Delete")
    todo_id = _extract_todo_id(create_res)

    delete_res = todo_tool.execute_action("delete", todo_id=todo_id)
    assert f"Todo {todo_id} deleted" in delete_res

    get_res = todo_tool.execute_action("get", todo_id=todo_id)
    assert "not found" in get_res


def test_isolation_and_default_tool_id(monkeypatch):
    """Ensure todos are isolated by tool_id and user_id."""
    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    # Same user, different tool_id
    tool1 = TodoListTool({"tool_id": "tool_1"}, user_id="u1")
    tool2 = TodoListTool({"tool_id": "tool_2"}, user_id="u1")

    r1_create = tool1.execute_action("create", title="from tool 1")
    r2_create = tool2.execute_action("create", title="from tool 2")

    r1 = tool1.execute_action("get", todo_id=_extract_todo_id(r1_create))
    r2 = tool2.execute_action("get", todo_id=_extract_todo_id(r2_create))

    assert "from tool 1" in r1
    assert "from tool 2" in r2

    # Same user, no tool_id → should default to same value
    t3 = TodoListTool({}, user_id="default_user")
    t4 = TodoListTool({}, user_id="default_user")

    assert t3.tool_id == "default_default_user"
    assert t4.tool_id == "default_default_user"

    create_res = t3.execute_action("create", title="shared default")
    r = t4.execute_action("get", todo_id=_extract_todo_id(create_res))

    assert "shared default" in r
