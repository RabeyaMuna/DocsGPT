import pytest
import re
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

    def find(self, query, projection=None):
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


def parse_create_response(response: str) -> dict:
    """Parse string response from create action."""
    # Format: "Todo created with ID {todo_id}: {title}"
    match = re.match(r"Todo created with ID (\d+): (.+)", response)
    if match:
        return {"status_code": 201, "todo_id": int(match.group(1))}
    elif response.startswith("Error:"):
        return {"status_code": 400, "todo_id": None}
    return {"status_code": 500, "todo_id": None}


def parse_list_response(response: str) -> dict:
    """Parse string response from list action."""
    if response.startswith("Todos:"):
        return {"status_code": 200, "todos": response}
    elif response == "No todos found.":
        return {"status_code": 200, "todos": []}
    elif response.startswith("Error:"):
        return {"status_code": 400, "todos": []}
    return {"status_code": 500, "todos": []}


def parse_get_response(response: str) -> dict:
    """Parse string response from get action."""
    # Format: "Todo [{todo_id}]:\nTitle: {title}\nStatus: {status}"
    match = re.match(r"Todo \[(\d+)\]:\nTitle: (.+)\nStatus: (.+)", response)
    if match:
        return {
            "status_code": 200,
            "todo": {
                "todo_id": int(match.group(1)),
                "title": match.group(2),
                "status": match.group(3)
            }
        }
    elif response.startswith("Error:") and "not found" in response:
        return {"status_code": 404, "todo": None}
    elif response.startswith("Error:"):
        return {"status_code": 400, "todo": None}
    return {"status_code": 500, "todo": None}


def parse_update_response(response: str) -> dict:
    """Parse string response from update action."""
    # Format: "Todo {todo_id} updated to: {title}"
    if response.startswith("Todo ") and "updated to:" in response:
        return {"status_code": 200}
    elif response.startswith("Error:") and "not found" in response:
        return {"status_code": 404}
    elif response.startswith("Error:"):
        return {"status_code": 400}
    return {"status_code": 500}


def parse_delete_response(response: str) -> dict:
    """Parse string response from delete action."""
    # Format: "Todo {todo_id} deleted."
    if response.startswith("Todo ") and "deleted." in response:
        return {"status_code": 200}
    elif response.startswith("Error:") and "not found" in response:
        return {"status_code": 404}
    elif response.startswith("Error:"):
        return {"status_code": 400}
    return {"status_code": 500}


def test_create_and_get(todo_tool: TodoListTool):
    res_str = todo_tool.execute_action("create", title="Write tests", description="Write pytest cases")
    res = parse_create_response(res_str)
    assert res["status_code"] == 201
    todo_id = res["todo_id"]

    get_res_str = todo_tool.execute_action("get", todo_id=todo_id)
    get_res = parse_get_response(get_res_str)
    assert get_res["status_code"] == 200
    assert get_res["todo"]["title"] == "Write tests"
    # Note: description is not stored/returned by the actual implementation


def test_get_all_todos(todo_tool: TodoListTool):
    todo_tool.execute_action("create", title="Task 1")
    todo_tool.execute_action("create", title="Task 2")

    list_res_str = todo_tool.execute_action("list")
    list_res = parse_list_response(list_res_str)
    assert list_res["status_code"] == 200
    # Check that both tasks are mentioned in the response
    assert "Task 1" in list_res["todos"]
    assert "Task 2" in list_res["todos"]


def test_update_todo(todo_tool: TodoListTool):
    create_res_str = todo_tool.execute_action("create", title="Initial Title")
    create_res = parse_create_response(create_res_str)
    todo_id = create_res["todo_id"]

    # Note: The update action only takes title, not updates dict
    update_res_str = todo_tool.execute_action("update", todo_id=todo_id, title="Updated Title")
    update_res = parse_update_response(update_res_str)
    assert update_res["status_code"] == 200

    get_res_str = todo_tool.execute_action("get", todo_id=todo_id)
    get_res = parse_get_response(get_res_str)
    assert get_res["todo"]["title"] == "Updated Title"


def test_delete_todo(todo_tool: TodoListTool):
    create_res_str = todo_tool.execute_action("create", title="To Delete")
    create_res = parse_create_response(create_res_str)
    todo_id = create_res["todo_id"]

    delete_res_str = todo_tool.execute_action("delete", todo_id=todo_id)
    delete_res = parse_delete_response(delete_res_str)
    assert delete_res["status_code"] == 200

    get_res_str = todo_tool.execute_action("get", todo_id=todo_id)
    get_res = parse_get_response(get_res_str)
    assert get_res["status_code"] == 404


def test_isolation_and_default_tool_id(monkeypatch):
    """Ensure todos are isolated by tool_id and user_id."""
    fake_collection = FakeCollection()
    fake_client = {settings.MONGO_DB_NAME: {"todos": fake_collection}}
    monkeypatch.setattr("application.core.mongo_db.MongoDB.get_client", lambda: fake_client)

    # Same user, different tool_id
    tool1 = TodoListTool({"tool_id": "tool_1"}, user_id="u1")
    tool2 = TodoListTool({"tool_id": "tool_2"}, user_id="u1")

    r1_create_str = tool1.execute_action("create", title="from tool 1")
    r1_create = parse_create_response(r1_create_str)
    r2_create_str = tool2.execute_action("create", title="from tool 2")
    r2_create = parse_create_response(r2_create_str)

    r1_str = tool1.execute_action("get", todo_id=r1_create["todo_id"])
    r1 = parse_get_response(r1_str)
    r2_str = tool2.execute_action("get", todo_id=r2_create["todo_id"])
    r2 = parse_get_response(r2_str)

    assert r1["status_code"] == 200
    assert r1["todo"]["title"] == "from tool 1"

    assert r2["status_code"] == 200
    assert r2["todo"]["title"] == "from tool 2"

    # Same user, no tool_id → should default to same value
    t3 = TodoListTool({}, user_id="default_user")
    t4 = TodoListTool({}, user_id="default_user")

    assert t3.tool_id == "default_default_user"
    assert t4.tool_id == "default_default_user"

    create_res_str = t3.execute_action("create", title="shared default")
    create_res = parse_create_response(create_res_str)
    r_str = t4.execute_action("get", todo_id=create_res["todo_id"])
    r = parse_get_response(r_str)

    assert r["status_code"] == 200
    assert r["todo"]["title"] == "shared default"
